import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from datetime import datetime, timezone, timedelta
import live_store
import bot_audit
import bot_controls
import bot_replay
import practice_executor as e


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.mock = patch.object(live_store, "DB_PATH", Path(self.folder.name)/"test.db")
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def test_audit_deduplicates_and_keeps_new_events_unread(self):
        for _ in range(3):
            bot_audit.emit("test", "Fill", "100", 1, notify=True)
        first = bot_audit.events()[0]["id"]
        self.assertEqual(len(bot_audit.events()),1)
        bot_audit.emit("test", "Fill", "101", 1, notify=True)
        bot_audit.acknowledge(first)
        self.assertEqual(len(bot_audit.events(unread=True)),1)

    def test_quote_check_uses_event_time_not_just_worker_heartbeat(self):
        now = datetime.now(timezone.utc)
        fresh = dict(feed_fresh=True,updated_at=now.isoformat(),quote_time=now.isoformat())
        self.assertTrue(e.quote_fresh(fresh,now))
        self.assertFalse(e.quote_fresh({**fresh,"quote_time":(now-timedelta(seconds=11)).isoformat()},now))
        self.assertFalse(e.quote_fresh({**fresh,"quote_time":(now+timedelta(seconds=1)).isoformat()},now))
        self.assertFalse(e.quote_fresh({"feed_fresh":True},now))

    def test_controls_and_sizing_do_not_arm_or_clear_safety(self):
        e.control(dict(enabled=False,after_id=44,start_balance=1000))
        bot_controls.save(["MNQ"],["CRT"],10)
        e.configure(dict(MNQ=3,MES=2,MYM=1),False)
        self.assertFalse(e.snapshot()[0]["enabled"])
        self.assertEqual(e.snapshot()[0]["start_balance"],1000)
        self.assertFalse(bot_controls.enabled("ES=F","CRT"))
        self.assertFalse(bot_controls.enabled("NQ=F","Reversal"))
        self.assertTrue(bot_controls.enabled("NQ=F","CRT"))
        with self.assertRaises(ValueError):
            bot_controls.save(["BAD"],["CRT"],5)

    def test_emergency_requires_confirmation_and_does_not_call_broker(self):
        e.control(dict(enabled=True))
        with patch.object(e,"call") as api:
            with self.assertRaises(ValueError):
                e.request_emergency_close(False)
            e.request_emergency_close(True)
            api.assert_not_called()
        self.assertFalse(e.snapshot()[0]["enabled"])
        self.assertTrue(e.snapshot()[0]["emergency_close"])

    def test_emergency_closes_only_owned_position_once(self):
        e.control(dict(enabled=False,emergency_close=True))
        e.claim(dict(alert_id=1,state="Open",symbol="MNQ",contract_id="MNQ",order_id=5,quantity=1,side=0,sent_at=0,signal_entry=100))
        position = dict(contractId="MNQ",size=1,type=1,averagePrice=100)
        order = dict(contractId="MNQ",parentOrderId=5,type=4,side=1,size=1)
        with patch.object(e,"verify_account",return_value={"balance":1000}), patch.object(e,"account_state",return_value=([position],[order])), patch.object(e,"alert_history",return_value=[]), patch.object(e,"call") as api:
            e.cycle("test")
            e.cycle("test")
        self.assertEqual(api.call_count,1)
        self.assertEqual(e.snapshot()[2][0]["state"],"Closing")

    def test_unowned_stop_does_not_count_as_protection(self):
        e.control(dict(enabled=False))
        e.claim(dict(alert_id=1,state="Open",symbol="MNQ",contract_id="MNQ",order_id=5,quantity=1,side=0,sent_at=0))
        with patch.object(e,"verify_account",return_value={"balance":1000}), patch.object(e,"account_state",return_value=([dict(contractId="MNQ",size=1,type=1,averagePrice=100)],[dict(contractId="MNQ",parentOrderId=99,type=4,side=1,size=1)])), patch.object(e,"alert_history",return_value=[]), patch.object(e,"call") as api:
            e.cycle("test")
        self.assertEqual(api.call_args[0][0],"/api/Position/closeContract")
        self.assertEqual(e.snapshot()[2][0]["close_reason"],"Missing verified broker stop")

    def test_replay_is_causal_and_does_not_write_live_state(self):
        bars = pd.DataFrame([dict(time=t,open=100.,high=102.,low=98.,close=100.) for t in pd.date_range("2026-09-15T18:00Z",periods=35,freq="min")])
        signal = dict(signal="LONG",entry=100.,stop=90.,target=110.)
        with patch.object(bot_replay,"evaluate_reversal",return_value=(signal,bars)), patch.object(bot_replay,"buffered_signal",side_effect=lambda s,b:s), patch.object(e,"call") as api:
            short = bot_replay.simulate(bars.iloc[:25],"NQ=F","Reversal")
            changed = bars.copy()
            changed.loc[30:,"low"] = 50
            full = bot_replay.simulate(changed,"NQ=F","Reversal")
            api.assert_not_called()
        self.assertTrue(short["open_at_end"])
        self.assertEqual(short["trades"],[])
        self.assertTrue(full["trades"])
        self.assertEqual(full["trades"][0]["exit"],90)
        self.assertEqual(e.snapshot()[2],[])

    def test_replay_session_filter_and_saved_results(self):
        bars = pd.DataFrame([dict(time=t,open=100.,high=102.,low=98.,close=100.) for t in pd.date_range("2026-09-15T18:00Z",periods=35,freq="min")])
        result = bot_replay.simulate(bars,"NQ=F","CRT",sessions=[])
        self.assertEqual(result["trades"],[])
        self.assertGreater(result["blocks"]["Session filter"],0)
        bot_replay.save_run({"strategy":"CRT"},result)
        self.assertEqual(bot_replay.saved_runs()[0]["result"],result)


if __name__ == "__main__":
    unittest.main()
