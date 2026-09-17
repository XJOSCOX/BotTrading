import unittest
from datetime import datetime

from market_session import CENTRAL, market_session, session_signal


class MarketSessionTests(unittest.TestCase):
    def test_boundaries(self):
        cases = [
            ("2026-09-16T08:29:59", "Overnight", True),
            ("2026-09-16T08:30:00", "Regular", True),
            ("2026-09-16T15:00:00", "Extended", True),
            ("2026-09-16T15:59:59", "Extended", True),
            ("2026-09-16T16:00:00", "Daily break", False),
            ("2026-09-16T17:00:00", "Overnight", True),
            ("2026-09-18T16:00:00", "Weekend closed", False),
            ("2026-09-19T18:00:00", "Weekend closed", False),
            ("2026-09-20T16:59:59", "Weekend closed", False),
            ("2026-09-20T17:00:00", "Overnight", True),
        ]
        for value, name, opened in cases:
            with self.subTest(value=value):
                result = market_session(datetime.fromisoformat(value).replace(tzinfo=CENTRAL))
                self.assertEqual((result["name"], result["is_open"]), (name, opened))

    def test_daylight_saving(self):
        for value in ["2026-01-14T14:30:00+00:00", "2026-07-15T13:30:00+00:00"]:
            self.assertEqual(market_session(datetime.fromisoformat(value))["name"], "Regular")

    def test_signal_pause_and_resume(self):
        signal = {"signal": "LONG", "entry": 100, "stop": 99, "target": 102}
        closed = market_session(datetime(2026, 9, 16, 16, tzinfo=CENTRAL))
        paused = session_signal(signal, closed)
        self.assertEqual(paused["signal"], "PAUSED")
        self.assertIsNone(paused["entry"])
        self.assertIsNone(paused["stop"])
        opened = market_session(datetime(2026, 9, 16, 17, tzinfo=CENTRAL))
        self.assertEqual(session_signal(signal, opened), signal)


if __name__ == "__main__":
    unittest.main()
