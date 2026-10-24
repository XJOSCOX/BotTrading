import unittest
from unittest.mock import patch
import pandas as pd

from goxtrade.bot.bot_monitor import evaluate_strategy_status
from goxtrade.strategies.strategy_catalog import LEGACY_STRATEGIES, strategy_spec
from goxtrade.strategies.entry_confirmation import window_open
from goxtrade.strategies.signal_candles import signal_candles
from tests.vwap_fixtures import minutes


class TimeframeTests(unittest.TestCase):
    def test_registry_preserves_legacy_timeframes_and_canonical_aliases(self):
        for name in LEGACY_STRATEGIES:
            spec = strategy_spec(name)
            self.assertEqual(spec.signal_minutes, 15)
            self.assertIs(strategy_spec(spec.id), spec)
        self.assertEqual(strategy_spec("VWAP EMA Cross").signal_minutes, 3)

    def test_monitor_uses_registered_adapter(self):
        result = dict(signal=dict(signal="WAIT"), timeframe="3 min")
        with patch("goxtrade.strategies.vwap_ema_runtime.evaluate_status", return_value=result) as evaluate:
            session = dict(time=pd.Timestamp("2026-10-02T00:21Z"), is_open=True)
            self.assertEqual(evaluate_strategy_status("NQ=F", "VWAP EMA Cross", session, pd.DataFrame()), result)
            evaluate.assert_called_once_with("NQ=F", "VWAP EMA Cross", session, True)

    def test_strategy_entry_window_uses_confirmation_not_fifteen_minutes(self):
        stamp = pd.Timestamp("2026-10-02T00:21Z")
        signal = dict(entry_policy="indicator-event-v1", entry_mode="CONFIRMED", signal_minutes=3,
                      setup_time=(stamp-pd.Timedelta(minutes=3)).isoformat(), confirmed_at=stamp.isoformat(),
                      entry_window_seconds=90)
        self.assertTrue(window_open(signal, stamp))
        self.assertFalse(window_open(signal, stamp-pd.Timedelta(seconds=1)))
        self.assertFalse(window_open(signal, stamp+pd.Timedelta(seconds=90)))

    def test_other_aggregation_intervals_unchanged(self):
        source = minutes([100.]*50)
        now = source.iloc[-1]["time"]+pd.Timedelta(minutes=1)
        for interval in (3, 5, 10, 15):
            frame = signal_candles(source, now, interval)
            for row in frame.to_dict("records"):
                self.assertEqual(row["volume"], interval)
                self.assertEqual(row["open"], 100.)
                self.assertLessEqual(row["time"]+pd.Timedelta(minutes=interval), now)
