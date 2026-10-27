"""Practice session regressions: all accounts, signals and transports are fixtures."""
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
import json
import time
import unittest
import sqlite3
from unittest.mock import patch

from tests import test_practice_order_roundtrip as roundtrip_fixtures
from tests.manager_fixtures import candidate, facts, policy, NOW, CONTRACT
from goxtrade.execution import practice_executor as executor, practice_automation as testing
from goxtrade.execution.strategy_manager import evaluate
from goxtrade.strategies.vwap_ema_config import VwapEmaConfig
from goxtrade.strategies.strategy_settings import read_vwap_ema_config
from goxtrade.bot import bot_controls
from goxtrade.config import execution_identity as identity
from tests import test_multi_symbol_entries as multi


class PracticeSessionTests(unittest.TestCase):
    setUp=roundtrip_fixtures.RoundTripTests.setUp

    def test_database_busy_retries_without_arming_or_overriding_manual_pause(self):
        with patch.object(executor,"pause") as pause,patch.object(executor,"status"),patch.object(executor.bot_audit,"emit"):
            self.assertTrue(executor.recover_connection(sqlite3.OperationalError("database is locked")))
            pause.assert_not_called()
            self.assertFalse(executor.recover_connection(sqlite3.OperationalError("disk I/O error")))
            pause.assert_called_once()

    def test_daily_counts_survive_session_restart_and_local_midnight(self):
        from datetime import datetime,timezone
        now=datetime(2026,10,27,6,tzinfo=timezone.utc)
        jobs=[dict(alert_id=i+1,state="Closed",strategy_testing_session="prior-session-"+str(i),sent_at=datetime(2026,10,27,h,30,tzinfo=timezone.utc).timestamp(),closed_confirmed_at=datetime(2026,10,27,h,45,tzinfo=timezone.utc).isoformat()) for i,h in enumerate((4,5))]
        settings=dict(enabled=True,after_id=0,start_balance=50000.,strategy_testing=dict(id="new-session",account_id=41,strategies=["vwap_ema_cross"],policy=policy().to_dict()))
        with patch("goxtrade.execution.contracts.contract_for_symbol",return_value=CONTRACT),patch("goxtrade.execution.practice_history.snapshot",return_value=({},[])),patch("goxtrade.execution.executed_results.results",return_value={1:dict(net=1.),2:dict(net=1.)}),patch.object(testing,"evaluate",return_value=[]) as manager:
            testing.selection(settings,[],dict(balance=50000.),dict(loss=0,locked=False),[],[],jobs,now=now)
        self.assertEqual(manager.call_args.args[1].daily_trades,2)

    def test_recovery_journal_failure_does_not_kill_executor_thread(self):
        with patch.object(executor,"snapshot",side_effect=sqlite3.OperationalError("database is locked")),patch.object(executor,"recover_connection",side_effect=sqlite3.OperationalError("database is locked")),patch.object(executor,"login") as login,patch.object(executor,"Event") as event:
            event.return_value.wait.side_effect=KeyboardInterrupt
            with self.assertRaises(KeyboardInterrupt):executor.run_practice()
            login.assert_not_called()

    def test_broker_manager_requires_explicit_practice_session_and_reconciliation(self):
        row=candidate(strategy="vwap_ema_cross",profile="practice")
        state=facts(profile="practice",armed=True,reconciled=True,practice_session_authorized=True)
        self.assertTrue(evaluate([row],state,policy(),NOW,scope="broker")[0].selected)
        for change in (dict(practice_session_authorized=False),dict(armed=False),dict(reconciled=False),dict(paused=True),dict(loss_locked=True),dict(unresolved=True)):
            self.assertFalse(evaluate([row],replace(state,**change),policy(),NOW,scope="broker")[0].selected)
        self.assertFalse(evaluate([candidate(profile="leader")],replace(state,profile="leader"),policy(),NOW,scope="broker")[0].selected)

    def test_start_uses_explicitly_confirmed_saved_sizes_preserves_limits_and_leader(self):
        settings=dict(enabled=False,max_trade_loss=500.,max_run_loss=500.,start_balance=50000.,quantities=dict(MNQ=3,MES=3,MYM=3),enable_mym=True)
        executor.control(settings)
        from goxtrade.execution.manager_service import save_policy
        save_policy(policy().to_dict())
        from goxtrade.strategies.strategy_settings import save_vwap_ema_config
        save_vwap_ema_config(VwapEmaConfig(entry_mode="REALTIME",signal_minutes=5,ema_length=12,enabled_symbols=("MNQ=F",)))
        with closing(executor.db()) as conn:
            before=conn.execute("SELECT settings,status FROM leader_control").fetchall()
        with patch.object(identity,"assert_current"),patch.object(executor,"assert_current"),patch.object(executor,"login",return_value="fixture"),patch.object(executor,"verify_account",return_value=self.broker.account),patch.object(executor,"account_state",return_value=([],[])),patch.object(executor.practice_safety,"check",return_value=dict(locked=False)),patch.object(executor,"alert_history",return_value=[]),patch.object(testing,"datetime") as clock,patch("goxtrade.market.calendar_guard.entry_block",return_value=None):
            clock.now.return_value=self.now
            session=testing.start(["vwap_ema_cross"],"PRAC-FIXTURE",True,confirmed_quantities=settings["quantities"])
        current=executor.snapshot()[0]
        self.assertTrue(current["enabled"])
        self.assertEqual(current["quantities"],settings["quantities"])
        self.assertEqual(current["max_trade_loss"],75.)
        self.assertEqual(current["max_run_loss"],500.)
        self.assertEqual(current["automation"]["id"],session["id"])
        config=read_vwap_ema_config()
        self.assertEqual((config.entry_mode,config.signal_minutes,config.ema_length,config.ema_source,config.vwap_source),("REALTIME",5,12,"close","ohlc4"))
        self.assertTrue(config.practice_enabled)
        self.assertFalse(config.leader_enabled)
        self.assertTrue(executor.symbol_enabled("NQ=F",current))
        self.assertTrue(executor.symbol_enabled("ES=F",current))
        self.assertTrue(executor.symbol_enabled("YM=F",current))
        with closing(executor.db()) as conn:
            self.assertEqual(before,conn.execute("SELECT settings,status FROM leader_control").fetchall())
        executor.pause()
        self.assertFalse(executor.snapshot()[0]["enabled"])
        self.network.assert_not_called()

    def test_start_rejects_wrong_account_leader_or_missing_confirmation(self):
        for name,confirmed in (("another-account",True),("PRAC-FIXTURE",False)):
            with self.assertRaises(ValueError):testing.start(["vwap_ema_cross"],name,confirmed,confirmed_quantities=None)
        with patch.object(identity,"PROFILE","leader"),self.assertRaises(ValueError):
            testing.start(["vwap_ema_cross"],"PRAC-FIXTURE",True,confirmed_quantities=None)

    def test_micro_monitor_uses_selected_micro_candles_trades_and_quote_freshness(self):
        import pandas as pd
        from goxtrade.strategies import vwap_ema_runtime as runtime
        now=pd.Timestamp(self.now)
        frame=pd.DataFrame(columns=["time"])
        candidate=dict(signal="WAIT",raw_signal="WAIT",reason="Fixture waiting",ema=None,vwap=None)
        with patch.object(runtime,"read_vwap_ema_config",return_value=VwapEmaConfig(enabled_symbols=("MNQ=F",))),patch.object(runtime,"contract_for_symbol",return_value=CONTRACT),patch.object(runtime,"load_strategy_minutes",return_value=frame) as load,patch.object(runtime,"latest_trade",return_value=dict(price=100.,id=1,event_time=now.isoformat(),received_at=now.isoformat())) as trade,patch.object(runtime.strategy_events,"observation",return_value={}),patch.object(runtime.strategy_events,"latest_event",return_value=None),patch.object(runtime.strategy_events,"persist",side_effect=lambda *args:args[-1]),patch.object(runtime,"evaluate_vwap_ema_cross",return_value=(candidate,frame,{})),patch.object(runtime,"track_signal",side_effect=lambda symbol,strategy,signal,*args:signal),patch("goxtrade.research.forward_paper.forward_once",return_value=None):
            result=runtime.evaluate_status("NQ=F","VWAP EMA Cross",dict(time=now,is_open=True))
        self.assertEqual(load.call_args.args[:2],("MNQ=F",CONTRACT))
        self.assertEqual(trade.call_args.args,("MNQ=F",CONTRACT))
        self.assertEqual(trade.call_args.kwargs,{"as_of":now})
        self.assertEqual(result["indicator_snapshot"]["reference_symbol"],"MNQ=F")
        self.assertTrue(result["source_feed_fresh"])

    def test_real_selection_uses_existing_manager_one_contract_and_blocks_loss_pause_conflict(self):
        now=self.now
        session=dict(id="session-fixture",account_id=41,strategies=["vwap_ema_cross"],policy=policy(symbols=("MNQ",)).to_dict())
        settings=dict(enabled=True,after_id=0,start_balance=50000.,strategy_testing=session)
        signal=dict(id=1,status="Active",strategy="VWAP EMA Cross",strategy_id="vwap_ema_cross",symbol="NQ=F",
                    signal="LONG",entry=100.,stop=90.,target=120.,unique_setup_id="source-fixture",detected_at=now.isoformat(),
                    confirmed_at=now.isoformat(),entry_window_seconds=90,entry_mode="CONFIRMED",signal_minutes=3,
                    config_snapshot=VwapEmaConfig().to_dict(),exit_mode="fixed")
        with patch("goxtrade.execution.contracts.contract_for_symbol",return_value=CONTRACT),patch("goxtrade.execution.practice_history.snapshot",return_value=({},[])),patch("goxtrade.data.strategy_history.latest_trade",return_value=dict(event_time=now.isoformat())),patch("goxtrade.strategies.entry_confirmation.check",return_value=dict(state="Confirmed",price=100.)),patch("goxtrade.strategies.strategy_catalog.order_block",return_value=None):
            selected=testing.selection(settings,[signal],dict(balance=50000.),dict(loss=0,locked=False),[],[],[],now=now)
            self.assertEqual(selected[1].quantity,1)
            for changed,gate,positions in (({**settings,"enabled":False},dict(loss=0,locked=False),[]),(settings,dict(loss=500,locked=True),[]),(settings,dict(loss=0,locked=False),[dict(id=1)])):
                self.assertFalse(testing.selection(changed,[signal],dict(balance=50000.),gate,positions,[],[],now=now))
            opposite={**signal,"id":2,"signal":"SHORT","stop":110.,"target":80.,"unique_setup_id":"other-fixture"}
            self.assertFalse(testing.selection(settings,[signal,opposite],dict(balance=50000.),dict(loss=0,locked=False),[],[],[],now=now))
            jobs=[dict(alert_id=1,state="Closed",sent_at=time.time())]
            self.assertFalse(testing.selection(settings,[signal],dict(balance=50000.),dict(loss=0,locked=False),[],[],jobs,now=now))
        self.assertFalse(self.broker.entered)
        self.network.assert_not_called()


class PracticeStrategyCycleTests(unittest.TestCase):
    setUp=multi.MultiSymbolTests.setUp
    cycle_mocks=multi.MultiSymbolTests.cycle_mocks

    def prepare(self):
        import pandas as pd
        from datetime import datetime
        from tests.vwap_fixtures import minutes
        from goxtrade.strategies.strategy_settings import save_vwap_ema_config
        from goxtrade.strategies.vwap_ema_cross import evaluate_vwap_ema_cross
        # Cover a complete futures session regardless of when this test is run.
        now=pd.Timestamp("2026-10-26T00:21:01Z")
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                value=now.to_pydatetime()
                return value.astimezone(tz) if tz else value.replace(tzinfo=None)
        self.stack.enter_context(patch.object(executor,"datetime",Clock))
        self.stack.enter_context(patch.object(testing,"datetime",Clock))
        config=save_vwap_ema_config(VwapEmaConfig(practice_enabled=True,enabled_symbols=("MNQ=F",),stop_method="fixed",entry_window_seconds=600))
        source=minutes(start=now.floor("3min")-pd.Timedelta(minutes=141))
        source.attrs["contract_id"]=CONTRACT
        signal=evaluate_vwap_ema_cross(source,103.,now,config,historical=True,symbol="MNQ=F")[0]
        self.assertEqual(signal["direction"],"LONG")
        signal.update(id=3,status="Active",strategy="VWAP EMA Cross",symbol="NQ=F",reference_symbol="MNQ=F",entry_time=now.isoformat())
        session=dict(id="cycle-fixture",account_id=executor.ACCOUNT_ID,strategies=["vwap_ema_cross"],policy=policy(symbols=("MNQ",)).to_dict())
        executor.update_settings(start_balance=50000.,max_trade_loss=500.,max_run_loss=500.,strategy_testing=session)
        bot_controls.save(["MNQ"],["VWAP EMA Cross"],5)
        self.cycle_mocks([],[signal])
        self.stack.enter_context(patch("goxtrade.market.calendar_guard.entry_block",return_value=None))
        self.stack.enter_context(patch.object(executor,"quote_fresh",return_value=True))
        self.stack.enter_context(patch.object(executor,"read_status",return_value={}))
        self.stack.enter_context(patch.object(executor.entry_confirmation,"check",side_effect=lambda signal,now=None:dict(state="Confirmed",reason="Mocked live revalidation",price=103.)))
        self.stack.enter_context(patch("goxtrade.execution.contracts.contract_for_symbol",return_value=CONTRACT))
        self.stack.enter_context(patch("goxtrade.execution.practice_history.snapshot",return_value=({},[])))
        self.stack.enter_context(patch("goxtrade.data.strategy_history.latest_trade",side_effect=lambda *args:dict(event_time=now.isoformat())))
        self.stack.enter_context(patch.object(executor,"call",return_value=dict(contracts=[dict(id=CONTRACT,symbolId="F.US.MNQ",activeContract=True)])))
        return self.stack.enter_context(patch.object(executor,"post",return_value=dict(success=True,errorCode=0,orderId=500)))

    def test_genuine_fixture_crossover_manager_claim_stop_and_no_duplicate(self):
        post=self.prepare()
        executor.cycle("fixture")
        self.assertEqual(post.call_count,1)
        payload=post.call_args.args[1]
        self.assertEqual((payload["accountId"],payload["contractId"],payload["size"],payload["side"]),(executor.ACCOUNT_ID,CONTRACT,1,0))
        self.assertEqual(payload["stopLossBracket"],dict(type=4,ticks=-12))
        self.assertEqual(executor.snapshot()[2][0]["reference_symbol"],"MNQ=F")
        executor.cycle("fixture")
        self.assertEqual(post.call_count,1)

    def test_pause_and_unknown_response_cannot_generate_repeated_entries(self):
        import requests
        post=self.prepare()
        executor.pause();executor.cycle("fixture")
        post.assert_not_called()
        executor.update_settings(enabled=True)
        post.side_effect=requests.Timeout("fixture uncertain response")
        with self.assertRaises(requests.Timeout):executor.cycle("fixture")
        self.assertEqual(executor.snapshot()[2][0]["state"],"Unknown")
        self.assertFalse(executor.snapshot()[0]["enabled"])
        executor.cycle("fixture")
        self.assertEqual(post.call_count,1)


if __name__=="__main__":unittest.main()
