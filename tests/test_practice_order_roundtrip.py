"""Controlled order tests use only fake transports, evidence and isolated databases."""
from contextlib import ExitStack, closing
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from unittest.mock import Mock, patch

import requests

from goxtrade.config import execution_identity as identity
from goxtrade.diagnostics import practice_validation as preflight
from goxtrade.execution import practice_executor as e, projectx_client as client
from goxtrade.execution.practice_order_store import TestStore, TestBlocked, digest
from goxtrade.execution.practice_test_reviews import evidence, review_account, review_calendar, account_review
from goxtrade.execution.practice_order_roundtrip import PracticeRoundTrip, PracticeBroker
from goxtrade.market import calendar_guard
from tests.test_practice_validation import TARGETS, ACCOUNT, CONTRACT


class FakeBroker:
    def __init__(self, clock):
        self.clock=clock; self.positions=[]; self.working=[]; self.orders=[]; self.trades=[]; self.entered=[]; self.closed=[]
        self.account=deepcopy(ACCOUNT); self.contract=deepcopy(CONTRACT)
        self.entry_error=None; self.close_error=None; self.ack=dict(success=True,errorCode=0,orderId=100)
        self.fill=True; self.protected=True; self.orphan=False

    def authenticate(self):
        pass

    def read(self,path,payload):
        if "accountId" in payload:
            assert payload["accountId"]==41, "Leader or another account reached transport"
        result={"/api/Account/search":[self.account],"/api/Contract/search":[self.contract],
                "/api/Position/searchOpen":self.positions,"/api/Order/searchOpen":self.working,
                "/api/Order/search":self.orders,"/api/Trade/search":self.trades}[path]
        return deepcopy(result)

    def enter(self,payload):
        self.entered.append(deepcopy(payload))
        order=dict(id=100,accountId=41,contractId=payload["contractId"],customTag=payload["customTag"],type=2,
                   size=1,side=payload["side"],status=2 if self.fill else 5 if self.ack["success"] is False else 6,fillVolume=1 if self.fill else 0)
        self.orders.append(order)
        if self.fill:
            price=100.25 if payload["side"]==0 else 100.
            self.positions=[dict(accountId=41,contractId=payload["contractId"],size=1,type=payload["side"]+1,averagePrice=price)]
            self.trades.append(dict(id=501,orderId=100,accountId=41,contractId=payload["contractId"],side=payload["side"],size=1,
                                    price=price,fees=.5,profitAndLoss=None,voided=False,creationTimestamp=self.clock().isoformat()))
            if self.protected:
                self.working=[dict(id=101,parentOrderId=100,accountId=41,contractId=payload["contractId"],type=4,status=1,
                                   side=1-payload["side"],size=1,stopPrice=price+payload["stopLossBracket"]["ticks"]*.25)]
        if self.entry_error:
            raise self.entry_error
        return deepcopy(self.ack)

    def close(self,job):
        assert job["account_id"]==41 and job["quantity"]==1
        self.closed.append(deepcopy(job))
        if self.close_error:
            raise self.close_error
        side=1-job["side"]; price=101. if side==1 else 99.
        self.orders.append(dict(id=102,accountId=41,contractId=job["contract_id"],type=2,side=side,size=1,status=2,fillVolume=1))
        self.trades.append(dict(id=502,orderId=102,accountId=41,contractId=job["contract_id"],side=side,size=1,
                                price=price,fees=.5,profitAndLoss=1.5,voided=False,creationTimestamp=self.clock().isoformat()))
        self.positions=[]
        if not self.orphan:
            self.working=[]


class RoundTripTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack(); self.addCleanup(self.stack.close)
        self.folder=Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.now=datetime(2026,10,26,18,tzinfo=timezone.utc)
        self.path=self.folder/"fixture.db"
        self.stack.enter_context(patch("goxtrade.data.live_store.DB_PATH",self.path))
        self.stack.enter_context(patch.object(identity,"current_targets",return_value=deepcopy(TARGETS)))
        self.stack.enter_context(patch.object(identity,"PROFILE","practice"))
        for key,value in (("PROFILE","practice"),("ACCOUNT_ID",41),("ACCOUNT_NAME","PRAC-FIXTURE"),("TARGET",TARGETS["practice"])):
            self.stack.enter_context(patch.object(e,key,value))
        self.stack.enter_context(patch.object(e.bot_audit,"emit"))
        self.network=self.stack.enter_context(patch.object(client.requests,"post",side_effect=AssertionError("Real network forbidden")))
        self.stack.enter_context(patch.object(calendar_guard,"CALENDAR_PATH",self.folder/"global-calendar-missing.json"))
        self.store=TestStore(self.path)
        with closing(e.db()) as conn:
            conn.execute("UPDATE practice_control SET settings=? WHERE id=1",(json.dumps(dict(enabled=False)),))
            conn.execute("CREATE TABLE leader_control(id INTEGER PRIMARY KEY,settings TEXT,status TEXT)")
            conn.execute("INSERT INTO leader_control VALUES(1,?,'{}')",(json.dumps(dict(enabled=False)),))
            conn.execute("CREATE TABLE leader_jobs(alert_id INTEGER PRIMARY KEY,record TEXT NOT NULL)")
            conn.commit()
        tick=dict(contract_id=CONTRACT["id"],price=100.25,best_bid=100.,best_ask=100.25,event_time=self.now.isoformat(),received_at=self.now.isoformat())
        self.local=dict(profiles={p:dict(settings=dict(enabled=False,start_balance=50000,max_run_loss=300),jobs=[]) for p in TARGETS},
                        gate=dict(account_id=41,baseline=50000,locked=False),policy=dict(cooldown_minutes=5),quote=deepcopy(tick),trade=deepcopy(tick))
        self.stack.enter_context(patch.object(preflight,"local_state",side_effect=lambda _:deepcopy(self.local)))
        self.broker=FakeBroker(lambda:self.now)
        self.flow=PracticeRoundTrip(self.store,self.broker,lambda:self.now)
        self.picture=self.folder/"provider-fixture.png"; self.picture.write_bytes(b"synthetic operator evidence, not a real provider screenshot")
        self.item=evidence(self.picture,"https://www.topstepx.com/trade")
        review_account(self.store,self.broker,self.item,self.item,lambda *_:True,self.now)
        self.calendar=self.folder/"reviewed-fixture.json"
        self.calendar.write_text(json.dumps(dict(schema_version=1,timezone="America/Chicago",source_url="https://www.cmegroup.com/trading-hours.html",
            product_group="US equity index futures",reviewed_at=self.now.isoformat(),valid_from=(self.now-timedelta(days=1)).isoformat(),valid_until=(self.now+timedelta(days=1)).isoformat(),
            sessions=[dict(open=(self.now-timedelta(hours=1)).isoformat(),close=(self.now+timedelta(hours=2)).isoformat())])))
        review_calendar(self.store,self.calendar,lambda *_:True,self.now)

    def propose(self,**changes):
        values=dict(side="BUY",stop_ticks=6,commission_per_side=.5,slippage_ticks=2,max_risk=20.)
        values.update(changes)
        return self.flow.propose(**values)

    def submit(self,**changes):
        record=self.propose(**changes)
        return self.flow.submit(record["id"],lambda *_:True)

    def advance(self,seconds):
        self.now+=timedelta(seconds=seconds)
        for key in ("quote","trade"):
            self.local[key].update(event_time=self.now.isoformat(),received_at=self.now.isoformat())

    def test_proposal_is_read_only_at_broker_and_contains_complete_risk(self):
        record=self.propose(); p=record["proposal"]
        self.assertEqual(p["quantity"],1); self.assertEqual(p["account_id"],41)
        self.assertEqual(p["planned_risk_usd"],6.)
        self.assertEqual(p["reference_stop"],98.75)
        self.assertTrue(p["leader_excluded"])
        self.assertFalse(self.broker.entered)

    def test_successful_mock_entry_stop_distinct_close_and_clean_reconciliation(self):
        record=self.submit()
        self.assertEqual(record["state"],"ACKNOWLEDGED")
        identifier=record["id"]
        protected=self.flow.reconcile(identifier)
        self.assertEqual(protected["state"],"PROTECTED")
        self.assertEqual(protected["entry_fill"],100.25)
        self.assertEqual(protected["stop_price"],98.75)
        self.assertFalse(self.broker.closed)
        self.flow.close_proposal(identifier)
        with self.assertRaises(TestBlocked):
            self.flow.close(identifier,lambda *_:False)
        self.flow.close(identifier,lambda *_:True)
        completed=self.flow.reconcile(identifier)
        self.assertEqual(completed["state"],"COMPLETE")
        self.assertEqual(completed["fees"],1.)
        self.assertEqual(completed["realized_pnl"],1.5)
        self.assertEqual(len(self.broker.entered),1); self.assertEqual(len(self.broker.closed),1)
        self.network.assert_not_called()

    def test_sell_payload_uses_correct_side_and_positive_stop_offset(self):
        self.submit(side="SELL")
        self.assertEqual(self.broker.entered[0]["side"],1)
        self.assertEqual(self.broker.entered[0]["stopLossBracket"],dict(type=4,ticks=6))

    def test_wrong_or_leader_account_is_rejected(self):
        for account in ({**ACCOUNT,"id":42},{**ACCOUNT,"name":"XFA-OTHER"},{**ACCOUNT,"canTrade":False}):
            self.broker.account=account
            with self.assertRaises(ValueError):
                self.propose()
        self.assertFalse(self.broker.entered)

    def test_leader_process_is_rejected(self):
        with patch.object(identity,"PROFILE","leader"),self.assertRaises(TestBlocked):
            self.propose()

    def test_missing_or_expired_category_oco_review_is_rejected(self):
        record=self.store.read("account",review=True)
        for changes in (dict(auto_oco=False),dict(category="combine"),dict(reviewed_at=(self.now-timedelta(hours=1)).isoformat()),dict(account_id=42)):
            self.store.review("account",{**record,**changes})
            with self.subTest(changes=changes),self.assertRaises(TestBlocked):self.propose()

    def test_review_rejection_or_changed_evidence_cannot_authorize(self):
        with self.assertRaises(TestBlocked):
            review_account(self.store,self.broker,self.item,self.item,lambda *_:False,self.now)
        self.picture.write_bytes(b"changed fixture")
        with self.assertRaises(TestBlocked):self.propose()

    def test_provider_evidence_rejects_non_provider_urls_and_secret_queries(self):
        for url in ("https://evil.example","https://topstepx.com/?token=secret","http://topstepx.com","https://user:secret@topstepx.com"):
            with self.subTest(url=url),self.assertRaises(TestBlocked):evidence(self.picture,url)

    def test_invalid_stop_side_costs_quantity_and_risk_are_blocked(self):
        for change in (dict(side=None),dict(stop_ticks=5),dict(stop_ticks=True),dict(stop_ticks=6.5),dict(max_risk=1),
                       dict(commission_per_side=0),dict(slippage_ticks=-1),dict(max_risk=float("nan"))):
            with self.subTest(change=change),self.assertRaises(TestBlocked):self.propose(**change)
        self.assertFalse(self.broker.entered)

    def test_stale_quotes_and_unreviewed_calendar_block(self):
        self.local["quote"]["event_time"]="2020-01-01T00:00:00Z"
        with self.assertRaises(TestBlocked):self.propose()
        self.local["quote"]["event_time"]=self.now.isoformat()
        self.calendar.write_text("{}")
        with self.assertRaises(TestBlocked):self.propose()

    def test_closed_market_or_existing_global_restriction_is_not_bypassed(self):
        with patch("goxtrade.execution.practice_order_roundtrip.execution_schedule",return_value=dict(allow_entry=False,flatten=True)),self.assertRaises(TestBlocked):self.propose()
        calendar_guard.CALENDAR_PATH.write_text("{}")
        with self.assertRaises(TestBlocked):self.propose()

    def test_open_positions_unknown_orders_and_unresolved_jobs_block(self):
        self.broker.positions=[dict(accountId=41,size=1)]
        with self.assertRaises(TestBlocked):self.propose()
        self.broker.positions=[]; self.broker.working=[dict(accountId=41,id=10)]
        with self.assertRaises(TestBlocked):self.propose()
        self.broker.working=[]; self.local["profiles"]["practice"]["jobs"]=[dict(state="Unknown")]
        with self.assertRaises(TestBlocked):self.propose()

    def test_loss_lock_and_automatic_strategy_permission_block(self):
        self.local["gate"]["locked"]=True
        with self.assertRaises(TestBlocked):self.propose()
        self.local["gate"]["locked"]=False; self.local["profiles"]["practice"]["settings"]["enabled"]=True
        with self.assertRaises(TestBlocked):self.propose()

    def test_expired_or_modified_proposal_needs_fresh_approval(self):
        record=self.propose(); self.advance(46)
        with self.assertRaises(TestBlocked):self.flow.submit(record["id"],lambda *_:True)
        record=self.propose()
        self.store.update(record["id"],("PROPOSED",),proposal={**record["proposal"],"side":"SELL"})
        with self.assertRaises(TestBlocked):self.flow.submit(record["id"],lambda *_:True)

    def test_changed_contract_and_price_conditions_block(self):
        record=self.propose()
        self.broker.contract["id"]="CON.F.US.MNQ.H27"
        for key in ("quote","trade"):self.local[key]["contract_id"]=self.broker.contract["id"]
        with self.assertRaises(TestBlocked):self.flow.submit(record["id"],lambda *_:True)
        self.broker.contract=deepcopy(CONTRACT)
        for key in ("quote","trade"):self.local[key]["contract_id"]=CONTRACT["id"]
        self.local["quote"].update(best_bid=101.,best_ask=101.25)
        with self.assertRaises(TestBlocked):self.flow.submit(record["id"],lambda *_:True)

    def test_declining_entry_does_not_consume_or_send(self):
        record=self.propose()
        with self.assertRaises(TestBlocked):self.flow.submit(record["id"],lambda *_:False)
        self.assertEqual(self.store.read(record["id"])["state"],"PROPOSED")
        self.assertFalse(self.broker.entered)

    def test_duplicate_confirmation_and_script_restart_never_resubmit(self):
        record=self.submit()
        restarted=PracticeRoundTrip(TestStore(self.path),self.broker,lambda:self.now)
        with self.assertRaises(TestBlocked):restarted.submit(record["id"],lambda *_:True)
        self.assertEqual(len(self.broker.entered),1)

    def test_timeout_unknown_entry_is_recovered_by_tag_without_retry(self):
        record=self.propose(); self.broker.entry_error=requests.Timeout("PRIVATE TOKEN")
        with self.assertRaises(TestBlocked):self.flow.submit(record["id"],lambda *_:True)
        self.assertEqual(self.store.read(record["id"])["state"],"SUBMISSION_UNKNOWN")
        with self.assertRaises(TestBlocked):self.flow.submit(record["id"],lambda *_:True)
        self.assertEqual(self.flow.reconcile(record["id"])["state"],"PROTECTED")
        self.assertNotIn("PRIVATE",json.dumps(self.store.read(record["id"])))

    def test_rejected_ack_with_order_id_requires_independent_reconciliation(self):
        self.broker.ack=dict(success=False,errorCode=2,orderId=100); self.broker.fill=False
        record=self.submit(); self.assertEqual(record["state"],"ACK_REJECTED")
        self.assertEqual(self.flow.reconcile(record["id"])["state"],"REJECTED")

    def test_malformed_ack_and_delayed_fill_do_not_prove_fill(self):
        self.broker.ack=dict(success="true",errorCode=0,orderId=100); self.broker.fill=False
        record=self.submit()
        self.assertEqual(record["state"],"SUBMISSION_UNKNOWN")
        self.assertEqual(self.flow.reconcile(record["id"])["state"],"SUBMISSION_UNKNOWN")

    def test_missing_protection_requires_explicit_emergency_close(self):
        self.broker.protected=False; record=self.submit()
        self.assertEqual(self.flow.reconcile(record["id"])["state"],"UNSAFE")
        with self.assertRaises(TestBlocked):self.flow.close_proposal(record["id"])
        self.flow.close_proposal(record["id"],emergency=True)
        self.assertFalse(self.broker.closed)
        self.flow.close(record["id"],lambda *_:True)
        self.assertEqual(self.flow.reconcile(record["id"])["state"],"COMPLETE")

    def test_partial_or_unowned_position_is_never_closed(self):
        record=self.submit(); self.broker.positions[0]["size"]=2
        with self.assertRaises(TestBlocked):self.flow.reconcile(record["id"])
        with self.assertRaises(TestBlocked):self.flow.close_proposal(record["id"],True)
        self.assertFalse(self.broker.closed)

    def test_close_timeout_and_restart_cannot_repeat_close(self):
        record=self.submit(); self.flow.close_proposal(record["id"])
        self.broker.close_error=requests.Timeout("PRIVATE CLOSE")
        with self.assertRaises(TestBlocked):self.flow.close(record["id"],lambda *_:True)
        restarted=PracticeRoundTrip(TestStore(self.path),self.broker,lambda:self.now)
        with self.assertRaises(TestBlocked):restarted.close(record["id"],lambda *_:True)
        self.assertEqual(len(self.broker.closed),1)

    def test_orphaned_protection_prevents_completion_and_is_not_canceled(self):
        record=self.submit(); self.flow.close_proposal(record["id"])
        self.broker.orphan=True; self.flow.close(record["id"],lambda *_:True)
        self.assertEqual(self.flow.reconcile(record["id"])["state"],"FLAT_RECONCILIATION_PENDING")
        self.assertEqual(len(self.broker.closed),1)

    def test_missing_fees_or_pnl_are_never_fabricated(self):
        record=self.submit(); self.flow.close_proposal(record["id"]); self.flow.close(record["id"],lambda *_:True)
        self.broker.trades[-1]["profitAndLoss"]=None
        self.assertEqual(self.flow.reconcile(record["id"])["state"],"FLAT_RECONCILIATION_PENDING")
        self.broker.trades[-1]["profitAndLoss"]=1.5; self.broker.trades[-1]["fees"]=None
        result=self.flow.reconcile(record["id"])
        self.assertEqual(result["state"],"COMPLETE"); self.assertIsNone(result["fees"])

    def test_concurrent_same_authorization_transmits_at_most_once(self):
        record=self.propose(); barrier=threading.Barrier(2)
        def run():
            try:return self.flow.submit(record["id"],lambda *_:barrier.wait(timeout=5) is not None)["state"]
            except TestBlocked:return "BLOCKED"
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:run(),range(2)))
        self.assertEqual(results.count("ACKNOWLEDGED"),1)
        self.assertEqual(len(self.broker.entered),1)

    def test_real_transport_requires_wire_reservation_and_exact_account(self):
        transport=PracticeBroker(self.store); transport.token="FIXTURE"
        with self.assertRaises(TestBlocked):transport.enter(dict(accountId=42,type=2,size=1))
        with self.assertRaises(TestBlocked):transport.enter(dict(accountId=41,type=2,size=1,customTag="gx-practice-validation-unknown"))
        self.network.assert_not_called()

    def test_noninteractive_approval_cannot_be_supplied_by_a_flag(self):
        from scripts.practice_execution_validation import confirm
        with patch("sys.stdin.isatty",return_value=False),self.assertRaises(TestBlocked):confirm({},"ENTER FIXTURE")

    def test_production_transport_mock_uses_existing_builder_and_full_close_once(self):
        record=self.propose(); identifier=record["id"]
        def route(path,payload,token=None):
            if path=="/api/Order/place":return self.broker.enter(payload)
            if path=="/api/Position/closeContract":
                self.broker.close(e.snapshot()[2][0]); return dict(success=True,errorCode=0)
            from goxtrade.execution.practice_order_roundtrip import READ_COLLECTIONS
            return dict(success=True,errorCode=0,**{READ_COLLECTIONS[path]:self.broker.read(path,payload)})
        transport=PracticeBroker(self.store,lambda:self.now)
        flow=PracticeRoundTrip(self.store,transport,lambda:self.now)
        with patch.object(client,"login",return_value="FIXTURE"),patch.object(client,"post",side_effect=route),patch.object(e,"post",side_effect=route):
            result=flow.submit(identifier,lambda *_:True)
            self.assertIsNotNone(result["wire_started_at"])
            with self.assertRaises(TestBlocked):transport.enter(self.broker.entered[0])
            flow.close_proposal(identifier)
            flow.close(identifier,lambda *_:True)
            self.assertEqual(e.snapshot()[2][0]["state"],"Closing")
            with self.assertRaises(TestBlocked):transport.close(e.snapshot()[2][0])
            self.assertEqual(flow.reconcile(identifier)["state"],"COMPLETE")
        self.assertEqual(len(self.broker.entered),1); self.assertEqual(len(self.broker.closed),1)

    def test_rejected_response_does_not_override_an_actual_broker_fill(self):
        self.broker.ack=dict(success=False,errorCode=2,orderId=100)
        record=self.submit()
        self.assertEqual(record["state"],"ACK_REJECTED")
        self.assertEqual(self.flow.reconcile(record["id"])["state"],"PROTECTED")

    def test_restart_during_entry_retains_sending_intent(self):
        record=self.propose()
        self.broker.enter=Mock(side_effect=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):self.flow.submit(record["id"],lambda *_:True)
        self.assertEqual(self.store.read(record["id"])["state"],"SENDING")
        restarted=PracticeRoundTrip(TestStore(self.path),self.broker,lambda:self.now)
        with self.assertRaises(TestBlocked):restarted.submit(record["id"],lambda *_:True)
        self.assertEqual(self.broker.enter.call_count,1)

    def test_restart_during_close_retains_close_intent(self):
        record=self.submit(); self.flow.close_proposal(record["id"])
        self.broker.close=Mock(side_effect=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):self.flow.close(record["id"],lambda *_:True)
        self.assertEqual(self.store.read(record["id"])["state"],"CLOSE_INTENT")
        with self.assertRaises(TestBlocked):self.flow.close(record["id"],lambda *_:True)
        self.assertEqual(self.broker.close.call_count,1)

    def test_distinct_concurrent_proposals_cannot_open_two_positions(self):
        records=[self.propose(),self.propose()]; barrier=threading.Barrier(2)
        def run(record):
            try:return self.flow.submit(record["id"],lambda *_:barrier.wait(timeout=5) is not None)["state"]
            except TestBlocked:return "BLOCKED"
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,records))
        self.assertEqual(results.count("ACKNOWLEDGED"),1)
        self.assertEqual(len(self.broker.entered),1)

    def test_concurrent_close_approvals_transmit_at_most_once(self):
        record=self.submit(); self.flow.close_proposal(record["id"]); barrier=threading.Barrier(2)
        def run():
            try:return self.flow.close(record["id"],lambda *_:barrier.wait(timeout=5) is not None)["state"]
            except TestBlocked:return "BLOCKED"
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:run(),range(2)))
        self.assertEqual(len(self.broker.closed),1)
        self.assertEqual(results.count("CLOSING"),1)

    def test_changed_close_position_and_expired_close_approval_block(self):
        record=self.submit(); self.flow.close_proposal(record["id"]); self.advance(46)
        with self.assertRaises(TestBlocked):self.flow.close(record["id"],lambda *_:True)
        self.flow.close_proposal(record["id"])
        def changed(*_):self.broker.positions[0]["size"]=2; return True
        with self.assertRaises(TestBlocked):self.flow.close(record["id"],changed)
        self.assertFalse(self.broker.closed)

    def test_transport_read_rejects_malformed_or_other_account_collections(self):
        transport=PracticeBroker(self.store); transport.token="FIXTURE"
        for result in ([],dict(success="true",errorCode=0,positions=[]),dict(success=True,errorCode=0,positions=[dict(accountId=42)]),dict(success=True,errorCode=0,positions=None)):
            with patch.object(client,"post",return_value=result),self.assertRaises(TestBlocked):
                transport.read("/api/Position/searchOpen",dict(accountId=41))


if __name__=="__main__":
    unittest.main()
