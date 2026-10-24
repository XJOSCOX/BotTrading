import unittest
import pandas as pd

from goxtrade.strategies.vwap_ema_config import VwapEmaConfig
from goxtrade.strategies.vwap_ema_indicators import session_anchor, indicator_frame
from tests.vwap_fixtures import minutes


class SessionTests(unittest.TestCase):
    def test_futures_and_rth_anchors_follow_chicago_dst(self):
        for stamp, expected in (("2026-01-15T23:30Z", "2026-01-15T23:00Z"),
                                ("2026-07-15T22:30Z", "2026-07-15T22:00Z")):
            self.assertEqual(session_anchor(stamp, VwapEmaConfig())[0], pd.Timestamp(expected))
        self.assertEqual(session_anchor("2026-07-15T15:00Z", VwapEmaConfig(anchor="rth"))[0], pd.Timestamp("2026-07-15T13:30Z"))

    def test_boundary_uses_wall_time_on_23_and_25_hour_days(self):
        for stamp, hours in (("2026-03-07T23:30Z", 23), ("2026-10-31T22:30Z", 25)):
            begin, end = session_anchor(stamp, VwapEmaConfig())
            self.assertEqual((end-begin).total_seconds()/3600, hours)

    def test_vwap_resets_and_truncated_session_is_not_calculated(self):
        first = minutes([100.]*20)
        second = minutes([200.]*20, "2026-10-04T22:00Z")
        frame = pd.concat([first, second], ignore_index=True)
        now = frame.iloc[-1]["time"]+pd.Timedelta(minutes=1)
        result = indicator_frame(frame, now)
        self.assertEqual(result.iloc[-1]["vwap"], 200.)
        truncated = indicator_frame(second.iloc[3:], now)
        self.assertTrue(truncated["vwap"].isna().all())

    def test_custom_anchor_and_rth_outside_window(self):
        config = VwapEmaConfig(anchor="custom", custom_anchor="18:00")
        self.assertEqual(session_anchor("2026-10-01T23:10Z", config)[0], pd.Timestamp("2026-10-01T23:00Z"))
        source = minutes([100.]*20, "2026-10-01T22:00Z")
        result = indicator_frame(source, source.iloc[-1]["time"]+pd.Timedelta(minutes=1), VwapEmaConfig(anchor="rth"))
        self.assertFalse(result["coverage"].any())
