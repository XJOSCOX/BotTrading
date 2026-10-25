import unittest
from dataclasses import replace
from goxtrade.strategies.previous_day_box import rejection, wick_metrics
from goxtrade.strategies.previous_day_box_config import PreviousDayBoxConfig


class WickTests(unittest.TestCase):
    def test_bullish_and_bearish_rejections(self):
        config=PreviousDayBoxConfig()
        self.assertTrue(rejection(dict(open=116,high=120,low=101,close=118),"LONG",config,.25))
        self.assertTrue(rejection(dict(open=184,high=199,low=180,close=182),"SHORT",config,.25))
        self.assertFalse(rejection(dict(open=110,high=120,low=109,close=119),"LONG",config,.25))

    def test_doji_no_division_by_zero_and_thresholds(self):
        bar=dict(open=118,high=120,low=100,close=118)
        config=PreviousDayBoxConfig(wick_body_enabled=True,wick_body_ratio=4,wick_range_enabled=True,wick_range_ratio=.5)
        self.assertEqual(wick_metrics(bar)["body"],0)
        self.assertTrue(rejection(bar,"LONG",config,.25))
        self.assertFalse(rejection(bar,"LONG",replace(config,wick_body_ratio=100),.25))
        self.assertFalse(rejection(bar,"LONG",replace(config,directional_close=True),.25))

    def test_invalid_zero_range_and_nan(self):
        for bar in (dict(open=1,high=1,low=1,close=1),dict(open=5,high=3,low=1,close=4),dict(open=float("nan"),high=3,low=1,close=2)):
            with self.assertRaises(ValueError):wick_metrics(bar)
