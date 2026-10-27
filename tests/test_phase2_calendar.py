from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from goxtrade.market import calendar_guard as calendar
from goxtrade.market.trading_schedule import execution_schedule


def reviewed():
    # Synthetic operator-reviewed windows, not a real exchange holiday calendar.
    return dict(schema_version=1, timezone="America/Chicago", source_url="https://www.cmegroup.com/trading-hours.html", product_group="US equity index futures",
                reviewed_at="2026-10-01T12:00:00Z", valid_from="2026-10-01T12:00:00Z", valid_until="2026-10-02T22:00:00Z",
                sessions=[dict(open="2026-10-01T13:30:00Z", close="2026-10-01T18:00:00Z"),
                          dict(open="2026-10-01T22:00:00Z", close="2026-10-02T21:00:00Z")])


class CalendarTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name)/"calendar.json"
        patcher = patch.object(calendar, "CALENDAR_PATH", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def install(self, values):
        # JSON fixture, not an app configuration or an actual approved schedule.
        self.path.write_text(json.dumps(values), encoding="utf-8")

    def test_missing_snapshot_preserves_legacy_but_blocks_new_strategy(self):
        now = pd.Timestamp("2026-10-01T15:00:00Z")
        self.assertTrue(execution_schedule(now)["allow_entry"])
        self.assertIsNotNone(calendar.entry_block(now))

    def test_reviewed_early_close_adds_cutoff_and_flatten_buffer(self):
        self.install(reviewed())
        self.assertTrue(execution_schedule(pd.Timestamp("2026-10-01T17:40:00Z"))["allow_entry"])
        self.assertFalse(execution_schedule(pd.Timestamp("2026-10-01T17:45:00Z"))["allow_entry"])
        self.assertTrue(execution_schedule(pd.Timestamp("2026-10-01T17:55:00Z"))["flatten"])
        self.assertTrue(execution_schedule(pd.Timestamp("2026-10-01T18:01:00Z"))["flatten"])

    def test_reviewed_windows_cannot_extend_topstep_or_weekend_schedule(self):
        self.install(reviewed())
        schedule = execution_schedule(pd.Timestamp("2026-10-02T20:10:00Z"))
        self.assertFalse(schedule["allow_entry"])
        self.assertTrue(schedule["flatten"])
        self.assertFalse(execution_schedule(pd.Timestamp("2026-10-03T15:00:00Z"), calendar=False)["allow_entry"])

    def test_stale_future_invalid_unknown_calendar_denies_without_guessing_flatten(self):
        for changes in (dict(reviewed_at="2026-09-01T12:00:00Z"), dict(reviewed_at="2026-10-02T12:00:00Z"),
                        dict(source_url="https://example.com/calendar"), dict(timezone="Invalid/Zone"),
                        dict(valid_until="2026-10-01T14:00:00Z")):
            self.install({**reviewed(), **changes})
            state = calendar.restriction(pd.Timestamp("2026-10-01T15:00:00Z"), required=True)
            self.assertFalse(state["allow_entry"], changes)
            self.assertFalse(state["flatten"], changes)

    def test_overlaps_and_timezone_naive_sessions_fail_closed(self):
        for sessions in ([dict(open="2026-10-01T13:30:00", close="2026-10-01T18:00:00")],
                         reviewed()["sessions"]+reviewed()["sessions"]):
            self.install(dict(reviewed(), sessions=sessions))
            self.assertIsNotNone(calendar.entry_block(pd.Timestamp("2026-10-01T15:00:00Z")))

    def test_dst_offsets_use_absolute_instants_not_fixed_offset_arithmetic(self):
        value = dict(reviewed(), reviewed_at="2026-10-30T12:00:00Z", valid_from="2026-10-30T12:00:00Z",
                     valid_until="2026-11-03T23:00:00Z", sessions=[dict(open="2026-11-01T17:00:00-06:00", close="2026-11-02T16:00:00-06:00")])
        self.install(value)
        self.assertFalse(calendar.restriction(pd.Timestamp("2026-11-01T22:30:00Z"))["allow_entry"])
        self.assertTrue(calendar.restriction(pd.Timestamp("2026-11-01T23:30:00Z"))["allow_entry"])

    def test_historical_simulation_does_not_read_todays_calendar_file(self):
        self.path.write_text("invalid", encoding="utf-8")
        now = pd.Timestamp("2026-10-01T15:00:00Z")
        self.assertFalse(execution_schedule(now)["allow_entry"])
        self.assertTrue(execution_schedule(now, calendar=False)["allow_entry"])

    def test_passive_review_reports_expiry_and_never_rewrites_calendar(self):
        self.install(reviewed())
        before=self.path.read_bytes()
        status=calendar.review_status(pd.Timestamp('2026-10-02T15:00:00Z'))
        self.assertTrue(status['valid'])
        self.assertTrue(status['expires_soon'])
        self.assertTrue(status['currently_open'])
        self.assertEqual(self.path.read_bytes(),before)
        expired=calendar.review_status(pd.Timestamp('2026-10-02T22:00:00Z'))
        self.assertFalse(expired['valid'])
        self.assertFalse(expired['currently_open'])
