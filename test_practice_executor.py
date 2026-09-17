import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import practice_executor as e
import live_store


class PracticeTests(unittest.TestCase):
    def test_mym_toggle_preserves_automation_and_safety_settings(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store,"DB_PATH",Path(folder)/"db"):
            settings = dict(enabled=False,start_balance=50000,after_id=42,quantities={"MNQ":3})
            e.control(settings)
            e.set_mym_enabled(True)
            self.assertEqual(e.snapshot()[0], {**settings,"enable_mym":True})
            e.set_mym_enabled(False)
            self.assertEqual(e.snapshot()[0], {**settings,"enable_mym":False})
    def test_mym_requires_explicit_activation(self):
        self.assertTrue(e.symbol_enabled("NQ=F",{}))
        self.assertTrue(e.symbol_enabled("ES=F",{}))
        self.assertFalse(e.symbol_enabled("YM=F",{}))
        self.assertFalse(e.symbol_enabled("YM=F",dict(enable_mym=False)))
        self.assertTrue(e.symbol_enabled("YM=F",dict(enable_mym=True)))
        self.assertFalse(e.symbol_enabled("UNKNOWN",dict(enable_mym=True)))
    def test_actual_fill_and_directional_slippage(self):
        for side, fill in ((0,101),(1,99)):
            job = dict(side=side, signal_entry=100)
            with patch.object(e,"save_job"):
                e.record_fill(job,dict(averagePrice=fill,size=2))
            self.assertEqual(job["fill_price"],fill)
            self.assertEqual(job["slippage_points"],1)
        with patch.object(e,"save_job") as save:
            with self.assertRaises(ValueError):
                e.record_fill({},dict(averagePrice=None,size=1))
            save.assert_not_called()
    def test_strategy_stop_preserves_selected_quantity_without_dollar_cap(self):
        signal = self.signal()
        signal["stop"] = 1
        order = e.build_order(signal,self.contract(),3)
        self.assertEqual(order["size"],3)
        self.assertEqual(order["stopLossBracket"]["ticks"],-396)
    def test_account_wide_wait_and_five_minute_cooldown(self):
        self.assertIsNotNone(e.entry_wait([{}],[],[],now=1000))
        self.assertIsNotNone(e.entry_wait([],[{}],[],now=1000))
        self.assertIsNotNone(e.entry_wait([],[],[dict(alert_id=1,state="Closing")],now=1000))
        job = dict(alert_id=1,state="Closed",closed_confirmed_at="1970-01-01T00:16:40+00:00")
        self.assertIn("0:01",e.entry_wait([],[],[job],now=1299))
        self.assertIsNone(e.entry_wait([],[],[job],now=1300))
        self.assertIsNone(e.entry_wait([],[],[dict(alert_id=2,state="Rejected")],now=1000))

    def test_opposing_exposure_across_symbols_and_pending_entries(self):
        self.assertTrue(e.opposing_exposure(1,[dict(type=1,contractId="MNQ")],[],[]))
        self.assertTrue(e.opposing_exposure(0,[],[dict(side=1)],[]))
        self.assertTrue(e.opposing_exposure(0,[],[],[dict(state="Submitted",side=1)]))
        self.assertFalse(e.opposing_exposure(0,[dict(type=1)],[],[]))

    def test_protective_sell_stop_is_not_a_short_entry(self):
        job = dict(state="Open",side=0,order_id=10,contract_id="MNQ",quantity=1)
        order = dict(parentOrderId=10,contractId="MNQ",type=4,side=1,size=1)
        self.assertFalse(e.opposing_exposure(0,[dict(type=1)],[order],[job]))
        self.assertTrue(e.opposing_exposure(0,[dict(type=1)],[{**order,"parentOrderId":99}],[job]))

    def test_cleanup_only_own_bracket_when_flat_and_no_retry(self):
        job = dict(alert_id=1, state="Closing", contract_id="MES", order_id=10, side=0, quantity=1)
        order = dict(id=11, contractId="MES", parentOrderId=10, type=4, side=1, size=1)
        with patch.object(e,"verify_account"), patch.object(e,"save_job"), patch.object(e,"account_state",return_value=([],[order])), patch.object(e,"call") as api:
            self.assertTrue(e.cleanup_stop(job,"test"))
            api.assert_called_once_with("/api/Order/cancel",dict(accountId=e.ACCOUNT_ID,orderId=11),"test")
            self.assertFalse(e.cleanup_stop(job,"test"))
            self.assertEqual(api.call_count,1)

    def test_cleanup_refuses_live_position_and_unrelated_order(self):
        job = dict(alert_id=1, state="Closing", contract_id="MES", order_id=10, side=0, quantity=1)
        for state in (([dict(contractId="MES")],[]), ([],[dict(contractId="MES",parentOrderId=99)])):
            with patch.object(e,"verify_account"), patch.object(e,"account_state",return_value=state), patch.object(e,"call") as api:
                self.assertFalse(e.cleanup_stop(job,"test"))
                api.assert_not_called()

    def signal(self):
        return dict(id=10,symbol="NQ=F",signal="LONG",entry=100,stop=95)

    def contract(self):
        return dict(id="CON.F.US.MNQ.Z26",symbolId="F.US.MNQ",activeContract=True)

    def test_practice_payload_and_stop(self):
        order = e.build_order(self.signal(),self.contract(),2,100)
        self.assertEqual(order["accountId"],e.ACCOUNT_ID)
        self.assertEqual(order["stopLossBracket"],dict(ticks=-20,type=4))
        self.assertNotIn("takeProfitBracket",order)
        self.assertEqual(order["size"],2)

    def test_rejects_minis_bad_size_and_risk(self):
        for quantity in (0,5,True):
            with self.assertRaises(ValueError):
                e.build_order(self.signal(),self.contract(),quantity,100)
        with self.assertRaises(ValueError):
            e.build_order(self.signal(),self.contract(),2,9)
        with self.assertRaises(ValueError):
            e.build_order(self.signal(),dict(id="CON.F.US.ENQ.Z26",symbolId="F.US.ENQ",activeContract=True),2,100)

    def test_rejects_combine_and_wrong_account(self):
        for account in (dict(id=e.ACCOUNT_ID,name="50KTC-TEST",simulated=True,canTrade=True),
                        dict(id=e.ACCOUNT_ID,name=e.ACCOUNT_NAME,simulated=False,canTrade=True),
                        dict(id=e.ACCOUNT_ID,name=e.ACCOUNT_NAME,simulated=True,canTrade=False)):
            with patch.object(e,"call",return_value={"accounts":[account]}):
                with self.assertRaises(RuntimeError):
                    e.verify_account("test")

    def test_duplicate_and_symbol_claims_survive_restart(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store,"DB_PATH",Path(folder)/"db"):
            job = dict(alert_id=1,contract_id="CON.F.US.MNQ.Z26",state="Intent")
            self.assertTrue(e.claim(job))
            self.assertFalse(e.claim(job))
            self.assertFalse(e.claim({**job,"alert_id":2}))
            self.assertEqual(e.snapshot()[2][0]["state"],"Intent")

    def test_arm_requires_confirmation_before_api(self):
        with patch.object(e,"login") as login:
            with self.assertRaises(ValueError):
                e.arm(100,300,False)
            login.assert_not_called()

    def test_disappeared_order_is_not_assumed_filled_and_closed(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store,"DB_PATH",Path(folder)/"db"):
            e.control(dict(enabled=False))
            e.claim(dict(alert_id=1, contract_id="CON.F.US.MYM.Z26", state="Submitted", sent_at=0))
            with patch.object(e, "verify_account", return_value={"balance":50000}), patch.object(e, "account_state", return_value=([], [])), patch.object(e, "alert_history", return_value=[]):
                e.cycle("test")
            self.assertEqual(e.snapshot()[2][0]["state"], "Unknown")

    def test_confirmed_flat_records_closed_and_keeps_transition(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store,"DB_PATH",Path(folder)/"db"):
            e.control(dict(enabled=False))
            e.claim(dict(alert_id=1, contract_id="CON.F.US.MYM.Z26", state="Open", fill_price=52000, sent_at=0))
            with patch.object(e, "verify_account", return_value={"balance":50000}), patch.object(e, "account_state", return_value=([], [])), patch.object(e, "alert_history", return_value=[]):
                e.cycle("test")
            self.assertEqual(e.snapshot()[2][0]["state"], "Closed")
            from contextlib import closing
            with closing(e.db()) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM practice_job_events").fetchone()[0], 1)

    def test_mym_minimum_stop_both_directions(self):
        contract = dict(id="CON.F.US.MYM.Z26", symbolId="F.US.MYM", activeContract=True)
        for direction, sign in (("LONG", 1), ("SHORT", -1)):
            for ticks in (1, 2, 3):
                signal = dict(id=1, symbol="YM=F", signal=direction, entry=52000, stop=52000-sign*ticks)
                with self.assertRaisesRegex(ValueError, "broker minimum is 4"):
                    e.build_order(signal, contract, 2, 100)
            signal = dict(id=1, symbol="YM=F", signal=direction, entry=52000, stop=52000-sign*4)
            self.assertEqual(e.build_order(signal, contract, 2, 100)["stopLossBracket"]["ticks"], -4 if direction == "LONG" else 4)
            with self.assertRaisesRegex(ValueError, "per-trade limit"):
                e.build_order(signal, contract, 2, 1)

    def test_size_reduced_without_increasing_risk(self):
        self.assertEqual(e.build_order(self.signal(), self.contract(), 4, 25)["size"], 2)
        self.assertEqual(e.build_order(self.signal(), self.contract(), 2, 10)["size"], 1)


if __name__ == "__main__":
    unittest.main()
