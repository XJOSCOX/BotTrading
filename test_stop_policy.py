import unittest
from datetime import datetime, timedelta, timezone
from stop_policy import buffered_signal, aggregate_minutes
from adaptive_exit import update_exit


class StopPolicyTests(unittest.TestCase):
    def test_higher_timeframes_use_swing_and_atr(self):
        start = datetime(2026,9,17,tzinfo=timezone.utc)
        for minutes in (5,10,15):
            bars = [dict(time=(start+timedelta(minutes=i)).isoformat(),high=102,low=98,close=100) for i in range(15*minutes)]
            for side,invalid,expected in (("LONG",99,96),("SHORT",101,104)):
                result = buffered_signal(dict(signal=side,entry=100,stop=invalid,target=110,tick_size=.25),bars,minutes)
                self.assertEqual(result["stop"],expected)
                self.assertEqual(result["management_minutes"],minutes)
                self.assertIn(f"{minutes}m ATR",result["trigger_detail"])
            self.assertEqual(len(aggregate_minutes(bars[:-1],minutes)),14)
            self.assertEqual(buffered_signal(dict(signal="LONG",entry=100,stop=99,tick_size=.25),bars[:-2]+bars[-1:],minutes)["signal"],"WAIT")

    def test_higher_timeframe_breaks_require_closed_bars(self):
        from test_adaptive_exit import active
        signal = active()
        signal["management_minutes"] = 5
        start = datetime.fromisoformat(signal["management_started_at"])
        bars = [dict(time=(start+timedelta(minutes=5*i)).isoformat(),closed_at=(start+timedelta(minutes=5*(i+1))).isoformat(),high=102,low=98,close=100 if i<3 else 97-i) for i in range(5)]
        update_exit(signal,bars,{"event_time":(start+timedelta(minutes=24)).isoformat()})
        self.assertEqual(signal["structure_breaks"],1)
        self.assertEqual(update_exit(signal,bars,{"event_time":(start+timedelta(minutes=25)).isoformat()}),"Structure break")
        self.assertIn("5m close",signal["exit_evidence"])

    def bars(self):
        start = datetime(2026, 9, 17, tzinfo=timezone.utc)
        return [dict(time=(start+timedelta(minutes=i)).isoformat(), high=102, low=98, close=100) for i in range(15)]

    def test_buffer_both_sides_and_tick_alignment(self):
        for direction, stop, expected in (("LONG", 99, 96), ("SHORT", 101, 104)):
            result = buffered_signal(dict(signal=direction, entry=100, stop=stop, target=110, tick_size=.25), self.bars())
            self.assertEqual(result["stop"], expected)
            self.assertEqual(result["trail_start_r"], 1.5)
            self.assertEqual(result["trail_buffer"], 2)

    def test_missing_minutes_block_new_entry(self):
        signal = dict(signal="LONG", entry=100, stop=99, target=110, tick_size=1)
        self.assertEqual(buffered_signal(signal, self.bars()[:-1])["signal"], "WAIT")
        bars = self.bars()
        bars[4]["time"] = bars[3]["time"]
        self.assertEqual(buffered_signal(signal, bars)["signal"], "WAIT")

    def test_buffered_trail_waits_until_one_and_half_r(self):
        from test_adaptive_exit import active, bar, tick
        signal = active()
        signal.update(trail_start_r=1.5, trail_buffer=2)
        bars = [bar(0,99,102,101),bar(1,100,104,103),bar(2,101,106,104),bar(3,103,108,107)]
        update_exit(signal,bars,tick(2,107,4))
        self.assertFalse(signal.get("trail_armed", False))
        bars.append(bar(4,104,110,108))
        update_exit(signal,bars,tick(3,108,5))
        self.assertTrue(signal["trail_armed"])
        self.assertEqual(signal["stop"],99)
