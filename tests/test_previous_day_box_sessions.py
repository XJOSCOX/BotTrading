import unittest
import pandas as pd
from goxtrade.strategies.previous_day_box_config import PreviousDayBoxConfig
from goxtrade.strategies.previous_day_box_sessions import previous_box, session_windows
from tests.previous_day_box_fixtures import NOW, CONTRACT, history


class BoxSessionTests(unittest.TestCase):
    def test_previous_session_not_current_high_low(self):
        frame=history()
        frame.loc[frame["time"]>pd.Timestamp("2026-10-22T22:00Z"),"high"]=999.
        box=previous_box(frame,NOW,PreviousDayBoxConfig(),CONTRACT)
        self.assertEqual((box["session_id"],box["pdh"]),("2026-10-22",200))

    def test_sunday_and_monday_use_friday(self):
        for now in (pd.Timestamp("2026-10-25T23:00Z"),pd.Timestamp("2026-10-26T14:00Z")):
            self.assertEqual(previous_box(history(now),now,PreviousDayBoxConfig(),CONTRACT)["session_id"],"2026-10-23")

    def test_saturday_does_not_invent_a_session(self):
        windows=session_windows(pd.Timestamp("2026-10-24T17:00Z"),PreviousDayBoxConfig())
        self.assertNotIn("2026-10-24",[row["id"] for row in windows])

    def test_dst_changes_utc_open_not_chicago_open(self):
        for day,hour in (("2026-10-26",22),("2026-11-02",23)):
            windows=session_windows(pd.Timestamp(day+"T16:00Z"),PreviousDayBoxConfig())
            row=next(row for row in windows if row["id"]==day)
            self.assertEqual(row["open"].hour,hour)
            self.assertEqual(row["open"].tz_convert("America/Chicago").hour,17)

    def test_holiday_and_early_close_from_exchange_calendar(self):
        windows=session_windows(pd.Timestamp("2026-11-27T16:00Z"),PreviousDayBoxConfig())
        holiday=next(row for row in windows if row["id"]=="2026-11-26")
        self.assertLess(holiday["close"].tz_convert("America/Chicago").hour,16)
        christmas=session_windows(pd.Timestamp("2026-12-28T16:00Z"),PreviousDayBoxConfig())
        self.assertNotIn("2026-12-25",[row["id"] for row in christmas])

    def test_rth_and_custom_explicit_boundaries(self):
        for config,start,end in ((PreviousDayBoxConfig(session="rth"),"08:30","15:00"),(PreviousDayBoxConfig(session="custom",custom_open="09:00",custom_close="14:00"),"09:00","14:00")):
            row=next(row for row in session_windows(NOW,config) if row["id"]=="2026-10-23")
            self.assertEqual((row["open"].tz_convert("America/Chicago").strftime("%H:%M"),row["close"].tz_convert("America/Chicago").strftime("%H:%M")),(start,end))

    def test_missing_incomplete_duplicate_and_rollover_fail_closed(self):
        for variant in ("missing","incomplete","duplicate","contract"):
            frame=history()
            if variant=="missing": frame=frame.drop(index=0)
            if variant=="incomplete": frame.loc[0,"complete"]=False
            if variant=="duplicate": frame=pd.concat([frame,frame.iloc[:1]],ignore_index=True)
            if variant=="contract": frame.attrs["contract_id"]="OTHER"
            with self.subTest(variant=variant),self.assertRaises(ValueError):
                previous_box(frame,NOW,PreviousDayBoxConfig(),CONTRACT)

    def test_future_availability_and_maintenance_gap(self):
        frame=history();frame["asof_time"]=NOW+pd.Timedelta(minutes=1)
        with self.assertRaises(ValueError):previous_box(frame,NOW,PreviousDayBoxConfig(),CONTRACT)
        self.assertEqual(sum(len(pd.date_range(a,b,freq="min",inclusive="left")) for a,b in session_windows(NOW,PreviousDayBoxConfig())[-3]["segments"]),1380)
