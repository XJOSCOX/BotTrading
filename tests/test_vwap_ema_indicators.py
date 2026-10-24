import unittest
import pandas as pd

from goxtrade.strategies.signal_candles import signal_candles
from goxtrade.strategies.vwap_ema_config import VwapEmaConfig
from goxtrade.strategies.vwap_ema_indicators import indicator_frame, price_source
from tests.vwap_fixtures import minutes


class IndicatorTests(unittest.TestCase):
    def test_ohlc4_and_variable_volume_vwap(self):
        frame = minutes([100.]*15+[102.])
        frame.loc[:2, ["open", "high", "low", "close"]] = [100., 106., 98., 104.]
        frame.loc[:2, "volume"] = 7.
        now = frame.iloc[-1]["time"]+pd.Timedelta(minutes=1)
        result = indicator_frame(frame, now)
        expected_sources = price_source(result, "ohlc4")
        expected = (expected_sources*result["volume"]).sum()/result["volume"].sum()
        self.assertAlmostEqual(result.iloc[-1]["vwap"], expected)
        self.assertEqual(result.iloc[0]["volume"], 21.)
        self.assertEqual(expected_sources.iloc[0], 102.)

    def test_standard_ema_recurrence_and_warmup(self):
        frame = minutes([100.]*45+[99., 103.])
        result = indicator_frame(frame, frame.iloc[-1]["time"]+pd.Timedelta(minutes=1))
        self.assertTrue(pd.isna(result.iloc[7]["ema"]))
        self.assertEqual(result.iloc[8]["ema"], 100.)
        self.assertAlmostEqual(result.iloc[-2]["ema"], 99.8)
        self.assertAlmostEqual(result.iloc[-1]["ema"], .2*103+.8*99.8)

    def test_missing_or_incomplete_buckets_and_duplicate_rejection(self):
        source = minutes([100.]*20)
        now = source.iloc[-1]["time"]
        self.assertEqual(len(signal_candles(source, now, 3, strict=True)), 19)
        self.assertEqual(len(signal_candles(source.drop(index=4), now, 3, strict=True)), 18)
        with self.assertRaises(ValueError):
            indicator_frame(pd.concat([source, source.iloc[:1]]), now)
        result = indicator_frame(source.drop(index=4), now)
        self.assertTrue(result.iloc[0]["coverage"])
        self.assertFalse(result.iloc[-1]["coverage"])

    def test_missing_invalid_and_zero_volume(self):
        for value in (None, -1, float("inf")):
            source = minutes()
            source.loc[10, "volume"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                indicator_frame(source, source.iloc[-1]["time"]+pd.Timedelta(minutes=1))
        source = minutes()
        source["volume"] = 0.
        result = indicator_frame(source, source.iloc[-1]["time"]+pd.Timedelta(minutes=1))
        self.assertTrue(result["vwap"].isna().all())

    def test_incompatible_anchor_and_invalid_parameters_rejected(self):
        for values in (dict(signal_minutes=4), dict(anchor="custom", custom_anchor="17:01"),
                       dict(timezone="not/a/zone"), dict(reward_risk=float("nan")),
                       dict(practice_enabled="yes"), dict(unknown=True)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                VwapEmaConfig.from_dict(values)
