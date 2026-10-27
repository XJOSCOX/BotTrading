"""Production adapter invariants; no network or live account mutation."""
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from goxtrade.execution.execution_policy import ExecutionPolicy
from goxtrade.execution.practice_automation import session_settings,job_session,validate_payload
from goxtrade.execution.portfolio_risk import authorize_risk
from goxtrade.data.history_recovery import recover_once
from tests.manager_fixtures import candidate,facts,policy,NOW


class ProductionAutomationTests(unittest.TestCase):
    def test_explicit_empty_strategies_never_reenable_saved_selection(self):
        from goxtrade.execution import practice_automation as automation,practice_executor as executor
        with patch.object(automation.identity,'PROFILE','practice'),patch.object(executor,'PROFILE','practice'),patch.object(automation.identity,'assert_current'),patch('goxtrade.bot.bot_controls.read',return_value=dict(strategies=['CRT'])),patch.object(executor,'arm') as arm:
            with self.assertRaisesRegex(ValueError,'Select unique registered'):
                automation.start([],executor.ACCOUNT_NAME,True,confirmed_quantities=dict(MNQ=1,MES=1,MYM=1))
            arm.assert_not_called()

    def test_legacy_session_keeps_frozen_one_contract_cap(self):
        old=dict(id="already-authorized",policy=policy(max_contracts=1).to_dict())
        settings=dict(strategy_testing=old,quantities=dict(MNQ=3))
        self.assertIs(session_settings(settings),old)
        self.assertEqual(session_settings(settings)["policy"]["max_contracts"],1)
        self.assertEqual(job_session(dict(strategy_testing_session="previous")),"previous")

    def test_per_symbol_quantity_is_bounded_by_user_and_risk(self):
        p=policy(symbol_quantities=(("MNQ",2),),requested_quantity=4,max_contracts=4)
        result=authorize_risk(candidate(),facts(),p,NOW)
        self.assertLessEqual(result["quantity"],2)
        with self.assertRaises(ValueError):
            ExecutionPolicy.from_dict({**p.to_dict(),"symbol_quantities":[["MNQ",5]]})

    def test_authorization_rejects_stale_or_unconfirmed_sizing(self):
        from goxtrade.execution import practice_automation as automation,practice_executor as executor
        saved=dict(enabled=False,quantities=dict(MNQ=3,MES=2,MYM=1))
        with patch.object(automation.identity,"PROFILE","practice"),patch.object(executor,"PROFILE","practice"),patch.object(automation.identity,"assert_current"),patch.object(executor,"snapshot",return_value=(saved,{},[])),patch("goxtrade.bot.bot_controls.read",return_value=dict(strategies=["CRT"])),patch.object(executor,"arm") as arm:
            for confirmed in (None,dict(MNQ=1,MES=2,MYM=1)):
                with self.assertRaises(ValueError):
                    automation.start(["crt"],executor.ACCOUNT_NAME,True,confirmed_quantities=confirmed)
            arm.assert_not_called()

    def test_exact_rounded_payload_cannot_exceed_budget_or_lost_account_headroom(self):
        settings=dict(start_balance=50000.,automation=dict(policy=policy().to_dict()))
        decision=SimpleNamespace(quantity=1,available_budget=75.)
        payload=dict(size=1,stopLossBracket=dict(ticks=-12))
        self.assertLess(validate_payload(settings,decision,payload,"MNQ",50000.,dict(loss=0,locked=False)),75)
        for ticks,loss in ((-160,0),(-12,499)):
            with self.assertRaises(ValueError):
                validate_payload(settings,decision,{**payload,"stopLossBracket":dict(ticks=ticks)},"MNQ",50000.,dict(loss=loss,locked=False))

    def test_history_recovery_retries_empty_failed_and_rolled_contracts(self):
        initialized=set(); reader=object()
        with patch("goxtrade.data.history_recovery.older_history_missing",return_value=False),patch("goxtrade.data.history_recovery.contract_for_symbol",return_value="first"),patch("goxtrade.data.history_recovery.backfill_history",side_effect=[0,20,10]) as fetch:
            recover_once(["MNQ=F"],initialized,reader)
            self.assertFalse(initialized)
            recover_once(["MNQ=F"],initialized,reader)
            recover_once(["MNQ=F"],initialized,reader)
            self.assertEqual([c.args[1] for c in fetch.call_args_list],[168,168,2])
        with patch("goxtrade.data.history_recovery.contract_for_symbol",return_value="rolled"),patch("goxtrade.data.history_recovery.backfill_history",side_effect=RuntimeError("fixture")) as fetch:
            result=recover_once(["MNQ=F"],initialized,reader)
            self.assertNotIn(("MNQ=F","rolled"),initialized)
            self.assertIn("unavailable",result["MNQ=F"])
            self.assertEqual(fetch.call_args.args[1],168)

    def test_partial_bootstrap_retries_old_history_without_clearing_saved_bars(self):
        initialized={('YM=F','fixture')}
        with patch('goxtrade.data.history_recovery.older_history_missing',side_effect=[True,False]), \
                patch('goxtrade.data.history_recovery.contract_for_symbol',return_value='fixture'), \
                patch('goxtrade.data.history_recovery.backfill_history',return_value=20) as fetch:
            recover_once(['YM=F'],initialized,object())
            recover_once(['YM=F'],initialized,object())
        self.assertEqual([call.args[1] for call in fetch.call_args_list],[168,2])

    def test_history_coverage_ignores_exchange_closures_but_detects_old_holes(self):
        import sqlite3
        import pandas as pd
        from goxtrade.data.history_recovery import older_history_missing
        from goxtrade.data.historical_quality import expected_minutes
        from datetime import datetime,timezone
        now=datetime(2026,10,27,5,0,tzinfo=timezone.utc)
        expected=expected_minutes(pd.Timestamp(now)-pd.Timedelta(hours=48),pd.Timestamp(now)-pd.Timedelta(hours=2))
        def database(missing=False):
            conn=sqlite3.connect(':memory:')
            conn.execute('CREATE TABLE strategy_historical_minutes(symbol,contract_id,time)')
            conn.executemany('INSERT INTO strategy_historical_minutes VALUES (?,?,?)',
                             [('YM=F','fixture',t.isoformat()) for t in (expected[:-1] if missing else expected)])
            return conn
        with patch('goxtrade.data.history_recovery.connect',side_effect=lambda:database()):
            self.assertFalse(older_history_missing('YM=F','fixture',48,now))
        with patch('goxtrade.data.history_recovery.connect',side_effect=lambda:database(True)):
            self.assertTrue(older_history_missing('YM=F','fixture',48,now))
        with patch('goxtrade.data.history_recovery.connect',side_effect=lambda:database()):
            self.assertTrue(older_history_missing('YM=F','different-contract',48,now))

    def test_history_download_chunks_are_bounded_and_invalid_data_is_not_persisted(self):
        from goxtrade.data import chart_history as history
        from datetime import datetime,timezone,timedelta
        now=datetime.now(timezone.utc).replace(second=0,microsecond=0)
        payloads=[]
        def response(path,payload):
            payloads.append(payload)
            stamp=payload['startTime']
            return dict(success=True,bars=[dict(t=stamp,o=100.,h=99.,l=98.,c=100.,v=1.)])
        with patch.object(history,'contract_for_symbol',return_value='fixture'),patch.object(history,'post',side_effect=response),patch.object(history,'connect') as connect:
            with self.assertRaises(ValueError):history.backfill_history('MNQ=F',hours=168)
            connect.assert_not_called()
        self.assertEqual(len(payloads),4)
        for payload in payloads:
            self.assertLessEqual(datetime.fromisoformat(payload['endTime'])-datetime.fromisoformat(payload['startTime']),timedelta(hours=48))
            self.assertEqual(payload['limit'],3000)


if __name__=="__main__":unittest.main()
