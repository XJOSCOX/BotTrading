import tempfile
import time
import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import live_store
import practice_executor as e


def job(number, symbol, quantity=1, state="Open"):
    return dict(alert_id=number, symbol=symbol, contract_id=f"CON.F.US.{symbol}.Z26",
                state=state, quantity=quantity, side=0, order_id=100+number,
                protected=True, sent_at=time.time()-120, fill_price=100)


def position(j):
    return dict(contractId=j["contract_id"], size=j["quantity"], type=j["side"]+1, averagePrice=100)


def stop(j):
    return dict(id=1000+j["alert_id"],contractId=j["contract_id"],parentOrderId=j["order_id"],
                type=4, side=1-j["side"], size=j["quantity"], stopPrice=95)


class MultiSymbolTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        folder = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch.object(live_store,"DB_PATH",Path(folder)/"db"))
        e.control(dict(enabled=True,after_id=0,enable_mym=True,quantities=dict(MNQ=3,MES=3,MYM=3)))

    def test_first_size_and_both_additions(self):
        a,b = job(1,"MNQ",2),job(2,"MES")
        self.assertEqual(e.entry_quantity(3,[],[]),3)
        for active, candidate in (([a],"MES"),([a,b],"MYM")):
            positions, orders = [position(j) for j in active],[stop(j) for j in active]
            self.assertIsNone(e.entry_wait(positions,orders,active,symbol=candidate))
            self.assertEqual(e.entry_quantity(3,positions,active),1)
        all_jobs = [a,b,job(3,"MYM")]
        self.assertIn("three",e.entry_wait([position(j) for j in all_jobs],[stop(j) for j in all_jobs],all_jobs))

    def test_same_symbol_missing_stop_unowned_and_pending_block(self):
        a = job(1,"MNQ",2)
        self.assertIn("same symbol",e.entry_wait([position(a)],[stop(a)],[a],symbol="MNQ"))
        self.assertIn("Protective stop",e.entry_wait([position(a)],[],[a],symbol="MES"))
        self.assertIn("Unrecognized working",e.entry_wait([position(a)],[dict(stop(a),parentOrderId=999)],[a]))
        self.assertIn("Unowned",e.entry_wait([dict(position(a),size=4)],[stop(a)],[a]))
        for state in ("Unknown","Intent","Submitted","Closing"):
            self.assertIn("unresolved",e.entry_wait([],[],[dict(a,state=state)]))

    def test_atomic_claim_serializes_and_caps_size(self):
        a = job(1,"MNQ",2)
        self.assertTrue(e.claim(a))
        self.assertFalse(e.claim(job(2,"MES",2,"Intent")))
        self.assertFalse(e.claim(job(2,"MNQ",1,"Intent")))
        self.assertFalse(e.claim(dict(job(2,"MES",1,"Intent"),side=1)))
        b = job(2,"MES",1,"Intent")
        self.assertTrue(e.claim(b))
        self.assertFalse(e.claim(job(3,"MYM",1,"Intent")))
        b["state"] = "Open"
        e.save_job(b)
        self.assertTrue(e.claim(job(3,"MYM")))
        self.assertFalse(e.claim(job(4,"MNQ")))

    def test_cooldown_remains_after_any_close(self):
        a = job(1,"MNQ",2)
        closed = dict(job(2,"MES"),state="Closed",closed_confirmed_at=datetime.now(timezone.utc).isoformat())
        self.assertIn("cooldown",e.entry_wait([position(a)],[stop(a)],[a,closed],symbol="MYM"))

    def cycle_mocks(self, active, signals):
        for j in active:
            self.assertTrue(e.claim(j))
        self.stack.enter_context(patch.object(e,"verify_account",return_value=dict(balance=50000)))
        self.stack.enter_context(patch.object(e,"account_state",return_value=([position(j) for j in active],[stop(j) for j in active])))
        self.stack.enter_context(patch.object(e,"alert_history",return_value=signals))
        self.stack.enter_context(patch.object(e,"market_session",return_value=dict(is_open=True)))

    def test_cycle_places_only_one_contract_for_second_and_third_symbol(self):
        a,b = job(1,"MNQ",2),job(2,"MES")
        self.cycle_mocks([a,b],[dict(id=3,status="Active",symbol="YM=F",strategy="CRT",signal="LONG",entry=52000,stop=51990,entry_time=datetime.now(timezone.utc).isoformat())])
        self.stack.enter_context(patch.object(e,"quote_fresh",return_value=True))
        self.stack.enter_context(patch.object(e,"read_status",return_value={}))
        self.stack.enter_context(patch.object(e,"call",return_value=dict(contracts=[dict(id="CON.F.US.MYM.Z26",symbolId="F.US.MYM",activeContract=True)])))
        api = self.stack.enter_context(patch.object(e,"post",return_value=dict(success=True,orderId=500)))
        e.cycle("test")
        payload = api.call_args.args[1]
        self.assertEqual(payload["size"],1)
        self.assertEqual(payload["contractId"],"CON.F.US.MYM.Z26")
        self.assertEqual(payload["stopLossBracket"]["ticks"],-10)
        self.assertEqual(api.call_count,1)
        self.assertEqual(e.snapshot()[2][0]["requested_quantity"],3)
        self.assertIn("capped at 1",e.snapshot()[2][0]["sizing_reason"])

    def test_emergency_manages_all_symbols_and_never_resends_closes(self):
        active = [job(1,"MNQ",2),job(2,"MES"),job(3,"MYM")]
        self.cycle_mocks(active,[])
        e.request_emergency_close(True)
        api = self.stack.enter_context(patch.object(e,"call",return_value=dict(success=True)))
        e.cycle("test")
        self.assertEqual(api.call_count,3)
        self.assertEqual({c.args[1]["contractId"] for c in api.call_args_list},{j["contract_id"] for j in active})
        self.assertTrue(all(j["state"]=="Closing" for j in e.snapshot()[2]))
        e.cycle("test")
        self.assertEqual(api.call_count,3)

    def test_unknown_job_does_not_starve_other_exit_management(self):
        a,b = job(1,"MNQ",2),job(2,"MES")
        self.cycle_mocks([a,b],[])
        b["state"] = "Unknown"
        e.save_job(b)
        e.request_emergency_close(True)
        api = self.stack.enter_context(patch.object(e,"call",return_value=dict(success=True)))
        e.cycle("test")
        self.assertEqual(api.call_count,1)
        self.assertEqual(api.call_args.args[1]["contractId"],a["contract_id"])

    def test_first_position_closes_before_preflight_no_size_increase(self):
        a = job(1,"MNQ",2)
        self.cycle_mocks([a],[dict(id=2,status="Active",symbol="ES=F",strategy="CRT",signal="LONG",entry=7700,stop=7695,entry_time=datetime.now(timezone.utc).isoformat())])
        self.stack.enter_context(patch.object(e,"quote_fresh",return_value=True))
        self.stack.enter_context(patch.object(e,"read_status",return_value={}))
        self.stack.enter_context(patch.object(e,"call",return_value=dict(contracts=[dict(id="CON.F.US.MES.Z26",symbolId="F.US.MES",activeContract=True)])))
        self.stack.enter_context(patch.object(e,"account_state",side_effect=[([position(a)],[stop(a)]),([],[])]))
        api = self.stack.enter_context(patch.object(e,"post"))
        e.cycle("test")
        api.assert_not_called()
        self.assertEqual(e.snapshot()[2][0]["state"],"Rejected")
