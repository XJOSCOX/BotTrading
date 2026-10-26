"""Phase 9 uses fixtures only. No test can authenticate or submit real orders."""
from contextlib import ExitStack, closing, redirect_stdout
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import importlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import requests

from goxtrade.diagnostics import practice_validation as v
from goxtrade.execution import practice_executor as e
from goxtrade.execution.strategy_manager import evaluate
from goxtrade.strategies.strategy_catalog import SPECS
from tests.manager_fixtures import NOW, candidate, facts, policy


STAMP = datetime(2026, 10, 26, 18, tzinfo=timezone.utc)
TARGETS = dict(practice=dict(id=41, name="PRAC-FIXTURE", role="Not assigned", gate_id=41),
               leader=dict(id=42, name="50KTC-FIXTURE", role="Leader", gate_id=42))
CONTRACT = dict(id="CON.F.US.MNQ.Z26", symbolId="F.US.MNQ", activeContract=True, tickSize=.25, tickValue=.5)
ACCOUNT = dict(id=41, name="PRAC-FIXTURE", simulated=True, canTrade=True, balance=50000)


def saved():
    settings = dict(enabled=False, start_balance=50000, max_run_loss=300)
    tick = dict(contract_id=CONTRACT["id"], event_time=STAMP.isoformat(), received_at=STAMP.isoformat(), price=100., best_bid=100., best_ask=100.25)
    return dict(profiles={p:dict(settings=deepcopy(settings), jobs=[]) for p in TARGETS},
                gate=dict(account_id=41, baseline=50000, locked=False), policy={}, quote=tick, trade=tick)


def responses(path, payload, token=None):
    key = v.READ_ENDPOINTS[path]
    rows = {"accounts":[ACCOUNT], "contracts":[CONTRACT], "positions":[], "orders":[],
            "bars":[dict(t="2026-10-26T17:59:00Z", o=100., h=101., l=99., c=100., v=12)]}[key]
    return dict(success=True, errorCode=0, **{key:deepcopy(rows)})


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.network = self.stack.enter_context(patch.object(v.client.requests, "post", side_effect=AssertionError("Real network forbidden")))
        self.stack.enter_context(patch.object(v.execution_identity, "current_targets", return_value=deepcopy(TARGETS)))
        self.state = saved()
        self.stack.enter_context(patch.object(v, "local_state", side_effect=lambda _:deepcopy(self.state)))
        self.stack.enter_context(patch.object(v, "market_session", return_value=dict(is_open=True, name="Regular")))
        self.stack.enter_context(patch.object(v, "execution_schedule", return_value=dict(allow_entry=True, flatten=False)))
        self.stack.enter_context(patch.object(v, "restriction", return_value=dict(allow_entry=True, flatten=False)))
        self.stack.enter_context(patch.object(v.feed_status, "read", return_value=dict(state="connected", error_code=None)))
        self.login = self.stack.enter_context(patch.object(v.client, "login", return_value="SECRET-TOKEN"))
        self.post = self.stack.enter_context(patch.object(v.client, "post", side_effect=responses))

    def collect(self):
        return v.collect(now=STAMP)

    def test_real_transport_is_absent_even_with_healthy_mock_evidence(self):
        before = deepcopy(self.state)
        report = self.collect()
        self.assertEqual(report["outcome"], "BLOCKED")
        self.assertEqual(report["actual_orders"], 0)
        self.assertIn("independent_provider_practice_category", report["blockers"])
        self.assertIn("provider_auto_oco_bracket_mode", report["blockers"])
        self.assertTrue(report["provider_calls_successful"])
        self.assertEqual(self.state, before)
        self.network.assert_not_called()
        for call in self.post.call_args_list:
            self.assertIn(call.args[0], v.READ_ENDPOINTS)
            if "accountId" in call.args[1]:
                self.assertEqual(call.args[1]["accountId"], 41)

    def test_read_boundary_rejects_order_close_cancel_modify_and_arming(self):
        broker = v.ReadOnlyBroker()
        broker.token = "fixture"
        for path in ("/api/Order/place", "/api/Order/cancel", "/api/Order/modify", "/api/Position/closeContract", "/api/execution/practice/arm"):
            with self.subTest(path=path), self.assertRaises(v.Blocked):
                broker.read(path, {"accountId":41})
        self.post.assert_not_called()

    def test_exact_allowlist_rejects_leader_funded_wrong_and_duplicate_accounts(self):
        for rows in ([{**ACCOUNT,"id":42}], [{**ACCOUNT,"name":"XFA-FIXTURE"}],
                     [{**ACCOUNT,"simulated":False}], [{**ACCOUNT,"canTrade":False}],
                     [ACCOUNT, ACCOUNT], [{**ACCOUNT,"balance":float("nan")}], []):
            with self.subTest(rows=rows), self.assertRaises(v.Blocked):
                v.exact_practice(rows,TARGETS)
        with self.assertRaises(v.Blocked):
            v.exact_practice([ACCOUNT], {**TARGETS,"practice":TARGETS["leader"]})

    def test_failed_identity_never_queries_exposure(self):
        self.post.side_effect = lambda path,payload,token:dict(success=True,errorCode=0,accounts=[{**ACCOUNT,"id":99}])
        report = self.collect()
        self.assertIn("exact_designated_identity_and_eligibility", report["blockers"])
        self.assertEqual(self.post.call_count,1)

    def test_simulation_and_name_do_not_establish_practice_category(self):
        report = self.collect()
        self.assertIn("independent_provider_practice_category", report["blockers"])
        self.assertNotIn("PRAC-FIXTURE",json.dumps(report))
        self.assertNotIn("SECRET-TOKEN",json.dumps(report))

    def test_contract_rejects_minis_wrong_specs_rollover_and_ambiguity(self):
        for changes in (dict(id="CON.F.US.ENQ.Z26"),dict(symbolId="F.US.ENQ"),dict(tickSize=1),
                        dict(tickValue=5),dict(activeContract=False),dict(tickValue=True)):
            with self.subTest(changes=changes), self.assertRaises(v.Blocked):
                v.active_mnq([{**CONTRACT,**changes}])
        with self.assertRaises(v.Blocked):
            v.active_mnq([CONTRACT,CONTRACT])

    def test_malformed_response_is_not_flat_or_accepted(self):
        broker = v.ReadOnlyBroker(); broker.token="fixture"
        for response in (None, [], dict(success="true",positions=[]), dict(success=True,positions=[]),
                         dict(success=True,errorCode=True,positions=[]),dict(success=True,errorCode=0,positions=None),
                         dict(success=True,errorCode=0,positions=[{}]),dict(success=True,errorCode=0,positions=[dict(accountId=42)])):
            self.post.side_effect = None; self.post.return_value=response
            with self.subTest(response=response), self.assertRaises(v.Blocked):
                broker.read("/api/Position/searchOpen",{"accountId":41})

    def test_rejection_and_timeout_are_sanitized_and_never_retried(self):
        broker = v.ReadOnlyBroker(); broker.token="fixture"
        self.post.side_effect = requests.Timeout("SECRET-KEY PRIVATE-ACCOUNT")
        with self.assertRaisesRegex(v.Blocked,"NETWORK_TIMEOUT"):
            broker.read("/api/Order/searchOpen",{"accountId":41})
        self.assertEqual(self.post.call_count,1)
        self.assertNotIn("SECRET",json.dumps(broker.evidence))
        self.post.side_effect=None
        self.post.return_value=dict(success=False,errorCode=2,errorMessage="SECRET-KEY",orders=[])
        with self.assertRaisesRegex(v.Blocked,"PROVIDER_REJECTED"):
            broker.read("/api/Order/searchOpen",{"accountId":41})
        self.assertNotIn("SECRET",json.dumps(broker.evidence))

    def test_authentication_failure_does_not_call_broker_or_retry(self):
        self.login.side_effect=v.client.ProjectXAuthError("SECRET")
        report=self.collect()
        self.login.assert_called_once()
        self.post.assert_not_called()
        self.assertNotIn("SECRET",json.dumps(report))

    def test_stale_future_wrong_contract_and_missing_bid_ask_block(self):
        for changes in (dict(event_time="2020-01-01T00:00:00Z"),dict(received_at="2026-10-27T00:00:00Z"),
                        dict(contract_id="CON.F.US.MNQ.H27"),dict(best_bid=None),dict(best_ask=99)):
            self.state=saved(); self.state["quote"]={**self.state["quote"],**changes}
            with self.subTest(changes=changes):
                self.assertIn("fresh_mnq_quote",self.collect()["blockers"])

    def test_open_positions_and_orphan_orders_are_reported_without_closing(self):
        def response(path,payload,token):
            data=responses(path,payload,token)
            if path in ("/api/Position/searchOpen","/api/Order/searchOpen"):
                data[v.READ_ENDPOINTS[path]]=[dict(accountId=41,id=9)]
            return data
        self.post.side_effect=response
        report=self.collect()
        self.assertIn("broker_positions_flat",report["blockers"])
        self.assertIn("broker_working_orders_clear",report["blockers"])
        self.assertTrue(all(c.args[0] in v.READ_ENDPOINTS for c in self.post.call_args_list))

    def test_risk_lock_and_saved_settings_are_not_changed(self):
        self.state["gate"]["locked"]=True
        self.state["gate"]["baseline"]=51000
        self.state["profiles"]["leader"]["settings"]["enabled"]=True
        self.state["profiles"]["practice"]["jobs"]=[dict(state="Unknown")]
        before=deepcopy(self.state)
        report=self.collect()
        for name in ("existing_500_loss_lock","current_balance_above_loss_lock","no_unresolved_local_jobs","practice_and_leader_paused"):
            self.assertIn(name,report["blockers"])
        self.assertEqual(before,self.state)

    def test_closed_session_and_missing_calendar_block(self):
        with patch.object(v,"market_session",return_value=dict(is_open=False,name="Closed")), \
                patch.object(v,"restriction",return_value=dict(allow_entry=False,flatten=True)):
            report=self.collect()
        self.assertIn("reviewed_exchange_calendar",report["blockers"])
        self.assertIn("exchange_standard_session",report["blockers"])

    def test_cli_and_retired_smoke_are_harmless_and_block_order_flag(self):
        from scripts import practice_execution_validation as script, practice_smoke_test as old
        self.assertIs(old.main,script.main)
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()), \
                patch.object(script,"collect",side_effect=self.collect):
            result=script.main(["--request-order","--output",str(Path(folder)/"evidence.json")])
            self.assertEqual(result,2)
            evidence=json.loads((Path(folder)/"evidence.json").read_text())
            self.assertEqual(evidence["actual_orders"],0)
        self.assertTrue(all(c.args[0] in v.READ_ENDPOINTS for c in self.post.call_args_list))

    def test_imports_do_not_authenticate(self):
        from scripts import practice_execution_validation, practice_smoke_test
        importlib.reload(practice_execution_validation); importlib.reload(practice_smoke_test)
        self.login.assert_not_called(); self.post.assert_not_called()

    def test_auth_failure_clears_previously_cached_probe_token(self):
        broker=v.ReadOnlyBroker(); broker.token="OLD-TOKEN"
        self.login.side_effect=v.client.ProjectXAuthError("Fixture")
        self.assertFalse(broker.authenticate())
        self.assertIsNone(broker.token)

    def test_invalid_or_unfinished_history_is_not_validated(self):
        for changes in (dict(h=98.),dict(t="2026-10-26T18:00:00Z"),dict(contractId="CON.F.US.MNQ.H27")):
            def response(path,payload,token):
                result=responses(path,payload,token)
                if path=="/api/History/retrieveBars":
                    result["bars"][0].update(changes)
                return result
            self.post.side_effect=response
            with self.subTest(changes=changes):
                self.assertIn("historical_ohlcv",self.collect()["blockers"])

    def test_local_snapshot_does_not_modify_or_initialize_production_store(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"local.db"
            with closing(sqlite3.connect(path)) as conn:
                conn.execute("CREATE TABLE practice_control(id INTEGER,settings TEXT)")
                conn.execute("INSERT INTO practice_control VALUES(1,?)",(json.dumps(dict(enabled=False)),))
                conn.commit()
            before=hashlib.sha256(path.read_bytes()).hexdigest()
            with patch.object(v.live_store,"DB_PATH",path):
                # Invoke the original reader, not this class's fixture replacement.
                result=type(self).real_local_state(TARGETS)
            self.assertFalse(result["profiles"]["practice"]["settings"]["enabled"])
            self.assertEqual(before,hashlib.sha256(path.read_bytes()).hexdigest())

    real_local_state=staticmethod(v.local_state)


class SevenStrategyPipelineTests(unittest.TestCase):
    def test_all_seven_confirmation_expiry_arbitration_direction_quantity_and_risk(self):
        self.assertEqual(len(SPECS),7)
        with patch.object(v.client.requests,"post",side_effect=AssertionError("No real transport")):
            for spec in SPECS:
                for direction, side in (("LONG",0),("SHORT",1)):
                    with self.subTest(strategy=spec.id,direction=direction):
                        row=candidate(spec.id,direction=direction)
                        decision=evaluate([row],facts(),policy(requested_quantity=1),NOW)[0]
                        self.assertTrue(decision.selected)
                        signal=dict(id=9,symbol="NQ=F",signal=direction,entry=row.entry_reference,stop=row.stop)
                        if spec.runtime_adapter is None:
                            signal.update(strategy_id=spec.id,strategy=spec.name,signal_minutes=15)
                        order=e.build_order(signal,CONTRACT,1)
                        self.assertEqual(order["side"],side)
                        self.assertEqual(order["size"],1)
                        self.assertEqual(order["contractId"],CONTRACT["id"])
                        self.assertEqual(order["stopLossBracket"]["type"],4)
                        self.assertEqual(order["stopLossBracket"]["ticks"]<0,side==0)
                        # Strategy-specific generation/envelope tests remain in their original suites.
                        for changed in (replace(row,confirmed=False),replace(row,history_complete=False),
                                        replace(row,expires_at="2026-10-22T14:59:59Z"),replace(row,account_id="leader")):
                            self.assertFalse(evaluate([changed],facts(),policy(),NOW)[0].selected)
                        self.assertFalse(evaluate([row],facts(loss_locked=True),policy(),NOW)[0].selected)
                        self.assertFalse(evaluate([row],facts(consumed=(row.setup_id,)),policy(),NOW)[0].selected)
                        self.assertFalse(evaluate([row],facts(),policy(),NOW,scope="broker")[0].selected)

    def test_indicator_and_box_generated_envelopes_reach_existing_payload_builder(self):
        import pandas as pd
        from goxtrade.strategies.vwap_ema_config import VwapEmaConfig
        from goxtrade.strategies.vwap_ema_cross import evaluate_vwap_ema_cross
        from goxtrade.strategies.previous_day_box_config import PreviousDayBoxConfig
        from tests.vwap_fixtures import minutes
        from tests.previous_day_box_fixtures import candidate as box_candidate, NOW as box_now
        with tempfile.TemporaryDirectory() as folder, patch.object(v.live_store,"DB_PATH",Path(folder)/"fixture.db"), \
                patch.object(v.client.requests,"post",side_effect=AssertionError("No real transport")), \
                patch("goxtrade.market.calendar_guard.entry_block",return_value=None):
            source=minutes(); source.attrs["contract_id"]="CON.F.US.ENQ.Z26"
            config=VwapEmaConfig(stop_method="fixed",practice_enabled=True)
            signal=evaluate_vwap_ema_cross(source,103.,source.iloc[-1]["time"]+pd.Timedelta(minutes=1),config,historical=True)[0]
            signal.update(id=8,symbol="NQ=F")
            with patch("goxtrade.strategies.strategy_settings.read_vwap_ema_config",return_value=config):
                self.assertEqual(e.build_order(signal,CONTRACT,1)["size"],1)
            signal=box_candidate(practice_enabled=True); signal.update(id=9,symbol="NQ=F")
            config=PreviousDayBoxConfig(practice_enabled=True)
            with patch("goxtrade.strategies.strategy_settings.read_previous_day_box_config",return_value=config),patch.object(e,"datetime") as clock:
                clock.now.return_value=box_now.to_pydatetime()
                self.assertEqual(e.build_order(signal,CONTRACT,1)["size"],1)


class ExistingExecutorMockRoundTripTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack(); self.addCleanup(self.stack.close)
        folder=self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch.object(v.live_store,"DB_PATH",Path(folder)/"execution.db"))
        self.stack.enter_context(patch.object(e,"ACCOUNT_ID",41))
        self.stack.enter_context(patch.object(e,"TARGET",TARGETS["practice"]))
        self.stack.enter_context(patch.object(e,"assert_current"))
        self.stack.enter_context(patch.object(e,"post",side_effect=AssertionError("Real transport forbidden")))
        self.stack.enter_context(patch.object(e,"verify_account",return_value=dict(balance=50000)))
        self.stack.enter_context(patch.object(e.practice_safety,"check",return_value=dict(locked=False)))
        self.stack.enter_context(patch.object(e.bot_audit,"emit"))
        self.stack.enter_context(patch.object(e.bot_health,"record"))
        self.stack.enter_context(patch.object(e,"alert_history",return_value=[]))
        self.stack.enter_context(patch("goxtrade.market.trading_schedule.execution_schedule",return_value=dict(allow_entry=True,flatten=False,reason="Fixture")))
        e.control(dict(enabled=False))
        self.job=dict(alert_id=-9,state="Intent",symbol="MNQ",contract_id=CONTRACT["id"],quantity=1,side=0,sent_at=0,signal_entry=100.)
        self.assertTrue(e.claim(self.job))
        self.job.update(state="Submitted",order_id=100)
        e.save_job(self.job)
        self.position=dict(accountId=41,contractId=CONTRACT["id"],size=1,type=1,averagePrice=100.5)
        self.stop=dict(id=101,accountId=41,contractId=CONTRACT["id"],parentOrderId=100,size=1,type=4,side=1,stopPrice=95.5)
        self.api=self.stack.enter_context(patch.object(e,"call",return_value=dict(success=True)))

    def cycle(self,positions,orders):
        with patch.object(e,"account_state",return_value=(positions,orders)):
            e.cycle("FIXTURE-TOKEN")
        return e.snapshot()[2][0]

    def test_successful_mock_fill_stop_full_close_and_flat(self):
        opened=self.cycle([self.position],[self.stop])
        self.assertEqual(opened["state"],"Open")
        self.assertEqual(opened["fill_price"],100.5)
        self.assertEqual(opened["slippage_points"],.5)
        self.assertTrue(opened["protected"])
        e.close_job(opened,"FIXTURE-TOKEN")
        self.api.assert_called_once_with("/api/Position/closeContract",dict(accountId=41,contractId=CONTRACT["id"]),"FIXTURE-TOKEN")
        self.assertEqual(self.cycle([],[])["state"],"Closed")

    def test_acknowledged_entry_not_observed_is_unknown_not_filled(self):
        self.assertEqual(self.cycle([],[])["state"],"Unknown")
        self.api.assert_not_called()

    def test_delayed_fill_is_pending_without_resubmission(self):
        self.job["sent_at"]=time.time(); e.save_job(self.job)
        self.assertEqual(self.cycle([],[])["state"],"Submitted")
        self.api.assert_not_called()

    def test_rejected_entry_not_retried(self):
        self.job["state"]="Rejected"; e.save_job(self.job)
        self.assertEqual(self.cycle([],[])["state"],"Rejected")
        self.api.assert_not_called()

    def test_duplicate_and_restart_cannot_claim_another_order(self):
        self.assertFalse(e.claim(self.job))
        self.assertFalse(e.claim({**self.job,"alert_id":-10}))
        self.assertEqual(len(e.snapshot()[2]),1)
        self.api.assert_not_called()

    def test_partial_or_mismatched_fill_requires_review(self):
        for size in (.5,2):
            self.assertEqual(self.cycle([{**self.position,"size":size}],[self.stop])["state"],"Submitted")
        self.assertFalse(e.snapshot()[0]["enabled"])
        self.api.assert_not_called()

    def test_missing_protection_uses_existing_full_close_safety_path(self):
        result=self.cycle([self.position],[])
        self.assertEqual(result["state"],"Closing")
        self.assertEqual(result["close_reason"],"Missing verified broker stop")
        self.assertEqual(self.api.call_count,1)
        self.assertEqual(self.api.call_args.args[1]["accountId"],41)

    def test_wrong_stop_side_quantity_parent_or_account_not_protection(self):
        for changes in (dict(side=0),dict(size=2),dict(parentOrderId=999),dict(accountId=42)):
            with self.subTest(changes=changes):
                self.assertFalse(e.protective_order({**self.stop,**changes},self.job))

    def test_unowned_position_is_not_closed(self):
        self.cycle([{**self.position,"contractId":"CON.F.US.MES.Z26"}],[])
        self.api.assert_not_called()

    def test_orphan_order_is_not_canceled_or_mistaken_for_flat(self):
        self.job.update(state="Open",fill_price=100.5); e.save_job(self.job)
        result=self.cycle([],[{**self.stop,"parentOrderId":999}])
        self.assertEqual(result["state"],"Open")
        self.api.assert_not_called()

    def test_close_timeout_is_persisted_and_never_repeated(self):
        opened=self.cycle([self.position],[self.stop])
        self.api.side_effect=requests.Timeout("Fixture unknown close")
        with self.assertRaises(requests.Timeout):
            e.close_job(opened,"FIXTURE-TOKEN")
        self.assertEqual(self.cycle([self.position],[self.stop])["state"],"Closing")
        self.assertEqual(self.api.call_count,1)
