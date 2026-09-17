import unittest

from signal_lifecycle import advance_signal


class SignalLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.signal = dict(signal="LONG", entry=100, stop=95, target=110, last_close=100)
        self.state, _ = advance_signal({}, self.signal, "a", [dict(id=1, price=100)])

    def test_target_clears_and_does_not_repeat(self):
        state, result = advance_signal(self.state, self.signal, "a", [dict(id=2, price=110), dict(id=3, price=99)])
        self.assertEqual(result["signal"], "WAIT")
        self.assertIn("Target reached", result["reason"])
        state, result = advance_signal(state, self.signal, "a", [dict(id=3, price=99)])
        self.assertIsNone(result["entry"])
        _, result = advance_signal(state, self.signal, "b", [dict(id=4, price=100)])
        self.assertEqual(result["signal"], "LONG")

    def test_fixed_levels_and_first_exit(self):
        changed = {**self.signal, "target": 120, "entry": 105}
        state, result = advance_signal(self.state, changed, "b", [dict(id=2, price=105)])
        self.assertEqual(result["target"], 110)
        self.assertEqual(result["entry"], 100)
        _, result = advance_signal(state, changed, "b", [dict(id=3, price=94), dict(id=4, price=120)])
        self.assertIn("Stop reached", result["reason"])

    def test_short_exits(self):
        signal = dict(signal="SHORT", entry=100, stop=105, target=90)
        for price, reason in [(90, "Target reached"), (105, "Stop reached")]:
            state, _ = advance_signal({}, signal, "a", [dict(id=1, price=100)])
            _, result = advance_signal(state, signal, "a", [dict(id=2, price=price)])
            self.assertIn(reason, result["reason"])

    def test_watch_does_not_activate(self):
        state, _ = advance_signal({}, {**self.signal, "signal": "LONG WATCH"}, "a", [dict(id=1, price=100)])
        self.assertFalse(state.get("active"))

    def test_invalid_levels(self):
        state, result = advance_signal({}, {**self.signal, "entry": 111}, "a", [dict(id=1, price=111)])
        self.assertFalse(state.get("active"))
        self.assertEqual(result["signal"], "WAIT")

    def test_stale_data_cannot_open_signal(self):
        state, result = advance_signal({}, self.signal, "a", [dict(id=1, price=100)], False)
        self.assertFalse(state.get("active"))
        self.assertEqual(result["signal"], "WAIT")


if __name__ == "__main__":
    unittest.main()
