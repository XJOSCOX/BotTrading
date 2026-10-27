"""Chart-only session VWAP, never used to alter trading decisions."""
import unittest
import pandas as pd
from goxtrade.market.chart_indicators import indicator_points


class ChartVwapTests(unittest.TestCase):
    def bars(self, times, volumes, closes):
        return pd.DataFrame([
            dict(time=pd.Timestamp(t), open=c, high=c+1, low=c-1, close=c, volume=v)
            for t, v, c in zip(times, volumes, closes)
        ])

    def test_weighted_hlc3_and_session_reset(self):
        points = indicator_points(self.bars(
            ["2026-10-26T22:00Z", "2026-10-26T22:01Z", "2026-10-27T22:00Z"],
            [2, 6, 3], [100, 104, 200]), "1min")
        self.assertEqual([p["vwap"] for p in points], [100, 103, 200])

    def test_missing_session_start_and_volume_are_not_estimated(self):
        points = indicator_points(self.bars(
            ["2026-10-26T22:01Z", "2026-10-27T22:00Z", "2026-10-27T22:01Z", "2026-10-27T22:02Z"],
            [2, 0, None, 4], [100, 101, 102, 103]), "1min")
        self.assertEqual([p["vwap"] for p in points], [None, None, None, None])

    def test_five_minute_candles(self):
        points = indicator_points(self.bars(
            ["2026-10-26T22:00Z", "2026-10-26T22:05Z"], [2, 6], [100, 104]), "5min")
        self.assertEqual([p["vwap"] for p in points], [100, 103])

    def test_dst_uses_chicago_session_start(self):
        points = indicator_points(self.bars(
            ["2026-11-02T23:00Z", "2026-11-02T23:01Z"], [2, 6], [100, 104]), "1min")
        self.assertEqual([p["vwap"] for p in points], [100, 103])

    def test_gap_invalidates_remaining_session(self):
        points = indicator_points(self.bars(
            ["2026-10-26T22:00Z", "2026-10-26T22:02Z"], [2, 6], [100, 104]), "1min")
        self.assertEqual([p["vwap"] for p in points], [100, None])
