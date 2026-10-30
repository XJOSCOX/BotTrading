"""Broker-backed labels must not mistake stale ownership for live exposure."""
import unittest
from datetime import datetime, timedelta, timezone
from goxtrade.api.state import job_display_state


class JobDisplayStateTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 30, 18, tzinfo=timezone.utc)
        self.job = dict(state="Open", account_id=42, contract_id="MES", quantity=2, side=1)
        self.position = dict(accountId=42, contractId="MES", size=2, type=2)
        self.health = dict(updated_at=self.now.isoformat(), positions=[self.position], error=False)

    def check(self, expected):
        self.assertEqual(job_display_state(self.job, self.health, 42, self.now), expected)

    def test_fresh_matching_position_is_in_trade(self):
        self.check("In Trade")
        self.job["state"] = "Closing"
        self.check("In Trade")

    def test_stale_or_missing_snapshot_is_not_in_trade(self):
        self.health["updated_at"] = (self.now-timedelta(seconds=31)).isoformat()
        self.check("Unverified")
        self.health = {}
        self.check("Unverified")

    def test_flat_snapshot_needs_reconciliation_not_watch_only(self):
        self.health["positions"] = []
        self.check("Reconciliation needed")

    def test_manual_position_or_other_account_cannot_establish_ownership(self):
        for key, value in [("contractId", "MNQ"), ("accountId", 43), ("size", 10), ("type", 1)]:
            with self.subTest(key=key):
                self.health["positions"] = [{**self.position, key: value}]
                self.check("Reconciliation needed")

    def test_failed_or_future_snapshot_is_unverified(self):
        self.health["error"] = True
        self.check("Unverified")
        self.health["error"] = False
        self.health["updated_at"] = (self.now+timedelta(seconds=1)).isoformat()
        self.check("Unverified")

    def test_closed_job_stays_closed_even_if_manual_position_matches(self):
        self.job["state"] = "Closed"
        self.check("Closed")
