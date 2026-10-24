import unittest
from dataclasses import replace
import pandas as pd

from goxtrade.strategies.vwap_ema_config import VwapEmaConfig
from goxtrade.strategies.vwap_ema_cross import evaluate_vwap_ema_cross
from tests.vwap_fixtures import minutes


class CrossTests(unittest.TestCase):
    def evaluate(self, frame, **kwargs):
        now = frame.iloc[-1]["time"]+pd.Timedelta(minutes=1)
        return evaluate_vwap_ema_cross(frame, float(frame.iloc[-1]["close"]), now,
                                       kwargs.pop("config", VwapEmaConfig(stop_method="fixed")),
                                       historical=True, **kwargs)

    def test_bullish_and_bearish_genuine_crosses(self):
        for closes, direction in (([100.]*45+[99., 103.], "LONG"), ([100.]*45+[101., 97.], "SHORT")):
            with self.subTest(direction=direction):
                signal, _, _ = self.evaluate(minutes(closes))
                self.assertEqual(signal["signal"], direction, signal["reason"])
                self.assertEqual(signal["signal_minutes"], 3)
                self.assertEqual(signal["strategy_id"], "vwap_ema_cross")
                self.assertEqual(signal["entry_mode"], "CONFIRMED")
                self.assertFalse(signal["provisional"])

    def test_remaining_above_is_not_another_cross(self):
        signal, _, _ = self.evaluate(minutes([100.]*45+[99., 103., 104.]))
        self.assertEqual(signal["signal"], "WAIT")
        self.assertEqual(signal["reason"], "No new crossover.")

    def test_confirmation_waits_until_bucket_closes_and_is_stable(self):
        source = minutes()
        close = source.iloc[-1]["time"]+pd.Timedelta(minutes=1)
        cfg = VwapEmaConfig(stop_method="fixed")
        early = evaluate_vwap_ema_cross(source, 103, close-pd.Timedelta(seconds=1), cfg, historical=True)[0]
        confirmed = evaluate_vwap_ema_cross(source, 103, close, cfg, historical=True)[0]
        again = evaluate_vwap_ema_cross(source, 103, close+pd.Timedelta(seconds=30), cfg, historical=True)[0]
        self.assertEqual(early["signal"], "WAIT")
        self.assertEqual(confirmed["signal"], "LONG")
        self.assertEqual(confirmed["unique_setup_id"], again["unique_setup_id"])
        future = pd.concat([source, minutes([999.], close)], ignore_index=True)
        self.assertEqual(evaluate_vwap_ema_cross(future, 103, close, cfg, historical=True)[0]["signal"], "LONG")

    def test_filters_are_independent_and_baseline_is_unfiltered(self):
        cfg = VwapEmaConfig(stop_method="fixed")
        baseline = self.evaluate(minutes(), config=cfg)[0]
        self.assertTrue(all(value == "disabled" for value in baseline["filter_results"].values()))
        blocked = self.evaluate(minutes(), config=replace(cfg, separation_enabled=True, separation_ticks=1000))[0]
        self.assertEqual(blocked["signal"], "WAIT")
        self.assertEqual(blocked["filter_results"]["separation"], "failed")

    def test_stale_data_and_missing_history_block_live_entries(self):
        source = minutes()
        now = source.iloc[-1]["time"]+pd.Timedelta(minutes=1)
        signal = evaluate_vwap_ema_cross(source, 103, now, VwapEmaConfig(stop_method="fixed"), quote_time=now-pd.Timedelta(seconds=11))[0]
        self.assertEqual(signal["signal"], "WAIT")
        self.assertIn("stale", signal["reason"])
        self.assertEqual(self.evaluate(source.drop(index=5))[0]["signal"], "WAIT")

    def test_risk_modes_tick_rounding_and_ratios(self):
        for method in ("fixed", "atr", "swing", "buffered"):
            for symbol in ("NQ=F", "ES=F", "YM=F"):
                signal, _, _ = self.evaluate(minutes(), config=VwapEmaConfig(stop_method=method, reward_risk=1.5), symbol=symbol)
                self.assertEqual(signal["signal"], "LONG", signal["reason"])
                tick = 1 if symbol == "YM=F" else .25
                for field in ("entry", "stop", "target"):
                    self.assertAlmostEqual(signal[field]/tick, round(signal[field]/tick))
                self.assertLess(signal["stop"], signal["entry"])
                self.assertGreaterEqual((signal["target"]-signal["entry"])/(signal["entry"]-signal["stop"]), 1.5)
