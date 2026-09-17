import unittest
from datetime import datetime, timedelta, timezone
from signal_lifecycle import advance_signal
from adaptive_exit import MODE, update_exit


BASE = datetime(2026, 9, 17, tzinfo=timezone.utc)


def bar(i, low, high, close):
    return dict(time=(BASE + timedelta(minutes=i)).isoformat(),
                closed_at=(BASE + timedelta(minutes=i + 1)).isoformat(),
                low=low, high=high, close=close)


def active(short=False):
    return dict(signal="SHORT" if short else "LONG", entry=100,
                stop=105 if short else 95, initial_stop=105 if short else 95,
                target=90 if short else 110, exit_mode=MODE, tick_size=.25,
                management_started_at=BASE.isoformat())


def tick(i, price, minute):
    return dict(id=i, price=price, event_time=(BASE + timedelta(minutes=minute)).isoformat())


class AdaptiveExitTests(unittest.TestCase):
    def test_targets_are_reference_both_directions(self):
        for short, value in ((False, 111), (True, 89)):
            signal = active(short)
            state, result = advance_signal(dict(active=signal, cursor=1), signal, "a", [tick(2, value, 1)])
            self.assertIsNotNone(state["active"])
            self.assertTrue(result["target_reached"])

    def test_protective_stop_and_no_mutation(self):
        signal = active()
        state = dict(active=signal, cursor=1)
        updated, _ = advance_signal(state, signal, "a", [tick(2, 94, 1)])
        self.assertEqual(updated["exit"], "Stop reached")
        self.assertIsNotNone(state["active"])

    def test_trail_arms_only_after_one_r_and_never_loosens(self):
        signal = active()
        bars = [bar(0,99,102,101), bar(1,100,104,103), bar(2,101,106,104), bar(3,103,108,107)]
        update_exit(signal, bars, tick(2,107,4))
        self.assertTrue(signal["trail_armed"])
        self.assertEqual(signal["stop"],99.75)
        bars.append(bar(4,98,108,104))
        update_exit(signal, bars, tick(3,104,5))
        self.assertEqual(signal["stop"],99.75)
        self.assertEqual(signal["initial_stop"],95)

    def test_short_trail(self):
        signal = active(True)
        bars = [bar(0,98,101,99), bar(1,96,100,97), bar(2,94,99,96), bar(3,92,97,93)]
        update_exit(signal,bars,tick(2,93,4))
        self.assertEqual(signal["stop"],100.25)

    def test_two_closes_exit_before_target(self):
        signal = active()
        bars = [bar(0,100,103,102), bar(1,100,103,102), bar(2,100,103,102),
                bar(3,99,102,99.5), bar(4,98,101,98.5)]
        self.assertIsNone(update_exit(signal,bars,tick(2,99.5,4)))
        self.assertEqual(update_exit(signal,bars,tick(3,98.5,5)), "Structure break")

    def test_no_future_candles_or_duplicate_processing(self):
        signal = active()
        bars = [bar(0,100,103,102),bar(1,100,103,102),bar(2,100,103,102),bar(3,99,102,99.5)]
        update_exit(signal,bars,tick(2,101,3.5))
        self.assertEqual(signal.get("structure_breaks",0),0)
        update_exit(signal,bars,tick(3,99.5,4))
        update_exit(signal,bars,tick(4,99.5,4.5))
        self.assertEqual(signal["structure_breaks"],1)

    def test_restart_keeps_trailing_stop(self):
        import json
        signal = active()
        signal["stop"] = 102
        signal["trail_armed"] = True
        state = json.loads(json.dumps(dict(active=signal,cursor=1)))
        state, _ = advance_signal(state,signal,"a",[tick(2,101,5)])
        self.assertEqual(state["exit"],"Trailing stop reached")


if __name__ == "__main__":
    unittest.main()
