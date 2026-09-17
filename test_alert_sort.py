import unittest

from bot_view import recent_alerts
from bot_view import prioritized_alerts


class AlertSortTests(unittest.TestCase):
    def test_in_trade_first_even_if_signal_closed(self):
        rows = [dict(id=i, status="Closed" if i == 1 else "Active", entry_time=f"2026-09-17T0{i}:00:00Z") for i in range(1, 5)]
        current, past = prioritized_alerts(rows, {1:dict(state="Open"), 2:dict(state="Closing")})
        self.assertEqual([r["id"] for r in current], [1,2,4,3])
        self.assertEqual(past, [])
    def test_active_uses_signal_time_not_id_or_updated_time(self):
        rows = [
            dict(id=10, status="Active", entry_time="2026-09-17T02:00:00Z", observed_at="2026-09-17T05:00:00Z"),
            dict(id=2, status="Active", entry_time="2026-09-16T22:00:00-05:00"),
        ]
        self.assertEqual([r["id"] for r in recent_alerts(rows)], [2, 10])
        self.assertEqual(rows[0]["id"], 10)

    def test_closed_uses_exit_time_before_entry_time(self):
        rows = [
            dict(id=10, status="Closed", entry_time="2026-09-17T03:00:00Z", exit_time="2026-09-17T04:00:00Z"),
            dict(id=2, status="Closed", entry_time="2026-09-17T02:00:00Z", exit_time="2026-09-17T05:00:00Z"),
        ]
        self.assertEqual([r["id"] for r in recent_alerts(rows)], [2, 10])

    def test_fallbacks_and_stable_ties(self):
        rows = [
            dict(id=1, status="Closed", exit_time="bad", entry_time="2026-09-17T02:00:00"),
            dict(id=2, status="Closed", entry_time="2026-09-17T02:00:00Z"),
            dict(id=3, status="Closed"),
        ]
        self.assertEqual([r["id"] for r in recent_alerts(rows)], [2, 1, 3])


if __name__ == "__main__":
    unittest.main()
