"""An expired hypothetical position is not an executable opposing signal."""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from goxtrade.execution import practice_executor as executor


class EntryConflictWindowTests(unittest.TestCase):
    def test_recorded_box_alert_and_expired_crt_watch(self):
        now = datetime(2026, 10, 28, 1, 0, 12, tzinfo=timezone.utc)
        old = dict(id=70, status="Active", symbol="ES=F", strategy="CRT", signal="LONG",
                   signal_minutes=15, setup_time="2026-10-28T00:00:00+00:00")
        new = dict(id=73, status="Active", symbol="ES=F", signal="SHORT",
                   entry_policy="previous-box-v1", entry_mode="CONFIRMED",
                   confirmed_at="2026-10-28T01:00:00+00:00", entry_window_seconds=90)
        with patch.object(executor, "PROFILE", "practice"):
            self.assertEqual(executor.entry_window_history([old, new], now), [new])
        self.assertEqual(old["status"], "Active")

    def test_current_opposite_stays_until_exact_expiry(self):
        signal = dict(status="Active", signal_minutes=15, setup_time="2026-10-28T00:45:00+00:00")
        with patch.object(executor, "PROFILE", "practice"):
            self.assertEqual(executor.entry_window_history([signal], datetime(2026,10,28,1,9,59,tzinfo=timezone.utc)), [signal])
            self.assertEqual(executor.entry_window_history([signal], datetime(2026,10,28,1,10,tzinfo=timezone.utc)), [])

    def test_leader_behavior_is_unchanged(self):
        expired = dict(status="Active", signal_minutes=15, setup_time="2026-10-28T00:00:00+00:00")
        with patch.object(executor, "PROFILE", "leader"):
            self.assertEqual(executor.entry_window_history([expired], datetime(2026,10,28,1,tzinfo=timezone.utc)), [expired])
