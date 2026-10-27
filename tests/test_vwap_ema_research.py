"""Synthetic prices verify arithmetic and causality, not trading profitability."""
from dataclasses import replace
import unittest
from unittest.mock import patch

import pandas as pd

from goxtrade.research.backtest import run_backtest, SimulationConfig
from goxtrade.research.forward_paper import advance_paper
from goxtrade.research.datasets import validate_ticks, UnsupportedDataset
from goxtrade.research.performance import comparison
from goxtrade.strategies.vwap_ema_config import VwapEmaConfig
from goxtrade.strategies.vwap_ema_cross import evaluate_vwap_ema_cross
from tests.vwap_fixtures import minutes


class ForwardPaperTests(unittest.TestCase):
    def setUp(self):
        calendar=patch("goxtrade.market.calendar_guard.restriction",return_value=dict(allow_entry=True,flatten=False))
        calendar.start();self.addCleanup(calendar.stop)
        self.config = VwapEmaConfig(paper_enabled=True, paper_zero_cost_sensitivity=True, stop_method="fixed", management_method="fixed", paper_slippage_ticks=0.)
        self.minutes = minutes()
        self.now = self.minutes.iloc[-1]["time"]+pd.Timedelta(minutes=1)
        self.signal = evaluate_vwap_ema_cross(self.minutes, 103., self.now, self.config, historical=True)[0]
        self.signal["detection_sequence"] = 1

    def tick(self, sequence, price, seconds=1):
        return dict(id=sequence, price=price, event_time=(self.now+pd.Timedelta(seconds=seconds)).isoformat())

    def advance(self, state, signal, ticks, seconds=1, config=None):
        return advance_paper(state, signal, ticks, self.minutes, "MNQ=F", "TEST.CONTRACT",
                             config or self.config, self.now+pd.Timedelta(seconds=seconds))

    def test_subsequent_trade_only_and_restart_safe_event_consumption(self):
        state, trades = self.advance(dict(cursor=1), self.signal, [])
        self.assertIsNone(state["active"])
        self.assertIsNotNone(state["pending"])
        state, _ = self.advance(state, self.signal, [self.tick(1, 103.), self.tick(2, 103.25)])
        self.assertEqual(state["active"]["entry"], 103.25)
        state, trades = self.advance(state, {}, [self.tick(3, 110., 2)], seconds=2)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["test_type"], "forward_paper")
        self.assertIsNone(state["active"])
        # Revisit an old event after another event and a process-style JSON round trip.
        state, _ = self.advance(state, {**self.signal, "unique_setup_id": "second"}, [])
        import json
        state = json.loads(json.dumps(state, default=str))
        state["pending"] = None
        state, _ = self.advance(state, self.signal, [])
        self.assertIsNone(state["pending"])

    def test_gap_fill_records_immediate_protective_loss_instead_of_cancellation(self):
        state, _ = self.advance(dict(cursor=1), self.signal, [])
        state, trades = self.advance(state, {}, [self.tick(2, 90.)])
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["entry"], 90.)
        self.assertIn("immediate protection", trades[0]["reason"])
        self.assertIsNone(state["active"])

    def test_disabling_entries_keeps_active_position_management_and_frozen_size(self):
        state, _ = self.advance(dict(cursor=1), self.signal, [])
        state, _ = self.advance(state, {}, [self.tick(2, 103.)])
        state, trades = self.advance(state, {}, [self.tick(3, 99., 2)], 2,
                                     replace(self.config, paper_enabled=False, paper_quantity=4, fixed_stop_ticks=1000))
        self.assertEqual(trades[0]["quantity"], 1)
        self.assertIsNone(state["active"])


class TickResearchTests(unittest.TestCase):
    def test_real_observations_fill_next_sequence_across_minute_boundary(self):
        cfg = VwapEmaConfig(entry_mode="REALTIME", stop_method="fixed", management_method="fixed")
        base = minutes([100.]*45+[99.])
        # Detection at the start of the second minute needs the actual first-minute snapshot.
        ticks = pd.DataFrame([
            dict(time="2026-10-02T00:18:59Z", sequence=1, price=99., volume=1.),
            dict(time="2026-10-02T00:19:01Z", sequence=2, price=105., volume=1.),
            dict(time="2026-10-02T00:19:02Z", sequence=3, price=106., volume=1.),
            dict(time="2026-10-02T00:19:03Z", sequence=4, price=115., volume=1.),
        ])
        result = run_backtest(base, "MNQ", "TEST.CONTRACT", strategy_config=cfg,
                              simulation=SimulationConfig(slippage_ticks=0, commission_per_side=0., zero_cost_sensitivity=True), ticks=ticks)
        self.assertEqual(result["tick_observations"], 4)
        self.assertEqual(len(result["trades"]), 1)
        self.assertEqual(result["trades"][0]["entry"], 106.)
        self.assertEqual(result["trades"][0]["entry_time"], "2026-10-02T00:19:02+00:00")

    def test_nonfinite_and_fractional_sequences_fail_closed(self):
        frame = pd.DataFrame([dict(time="2026-10-02T00:18:01Z", sequence=1, price=100., volume=1.)])
        for field, value in (("sequence", 1.5), ("price", float("inf")), ("volume", -1), ("sequence", 0)):
            data = frame.copy()
            data[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(UnsupportedDataset):
                validate_ticks(data, "TEST.CONTRACT")

    def test_comparison_never_pools_test_types_or_historical_runs(self):
        common = dict(strategy="VWAP EMA Cross", symbol="MNQ", timeframe=3, entry_mode="CONFIRMED",
                      exit_time="2026-10-02T00:20:00Z", net=5., session="Overnight")
        rows = [{**common, "test_type": kind, "comparison_context": context}
                for kind, context in (("historical_backtest", "run 1"), ("historical_backtest", "run 2"),
                                      ("forward_paper", "paper"), ("broker_practice", "actual"))]
        output = comparison(rows)
        self.assertEqual(len(output), 4)
        self.assertTrue(all(row["trades"] == 1 for row in output))

    def test_strategy_chart_uses_same_indicators_and_only_completed_historical_markers(self):
        from goxtrade.ui.bot.strategy_chart import chart_payload
        frame = minutes()
        now = frame.iloc[-1]["time"]+pd.Timedelta(minutes=1)
        cfg = VwapEmaConfig(stop_method="fixed")
        signal, candles, _ = evaluate_vwap_ema_cross(frame, 103., now, cfg, historical=True)
        payload = chart_payload(candles, cfg, signal=signal)
        self.assertEqual(payload["points"][-1]["strategy_ema"], candles.iloc[-1]["ema"])
        self.assertEqual(payload["points"][-1]["strategy_vwap"], candles.iloc[-1]["vwap"])
        self.assertEqual(payload["markers"][-1]["text"], "Confirmed cross")
        self.assertEqual(payload["levels"]["stop"], signal["stop"])
