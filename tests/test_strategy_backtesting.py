from dataclasses import replace
import unittest
import pandas as pd

from goxtrade.market.instruments import instrument
from goxtrade.research.backtest import SimulationConfig, run_backtest, chronological_splits
from goxtrade.research.datasets import UnsupportedDataset
from goxtrade.research.metrics import statistics
from goxtrade.strategies.vwap_ema_config import VwapEmaConfig
from tests.vwap_fixtures import minutes


def long_fixture():
    return minutes([101.]*5+[99.]*41+[103., 104., 111.])


class BacktestTests(unittest.TestCase):
    def setUp(self):
        self.config = VwapEmaConfig(stop_method="fixed", management_method="fixed")
        self.sim = SimulationConfig(slippage_ticks=0)

    def run_model(self, frame, symbol="MNQ", config=None, simulation=None, **kwargs):
        return run_backtest(frame, symbol, "TEST.CONTRACT", strategy_config=config or self.config,
                            simulation=simulation or self.sim, **kwargs)

    def test_next_minute_open_fill_commission_and_correct_contract_multiplier(self):
        frame = long_fixture()
        result = self.run_model(frame, simulation=replace(self.sim, quantity=2, commission_per_side=.5))
        self.assertEqual(len(result["trades"]), 1)
        trade = result["trades"][0]
        self.assertEqual(trade["direction"], "LONG")
        self.assertEqual(trade["entry"], 104.)
        self.assertNotEqual(trade["entry"], 103.)
        self.assertEqual(trade["entry_time"], frame.iloc[141]["time"].isoformat())
        self.assertEqual(trade["exit"], 110.)
        self.assertEqual(trade["gross"], 24.)
        self.assertEqual(trade["costs"], 2.)
        self.assertEqual(trade["net"], 22.)
        self.assertEqual(result["test_type"], "historical_backtest")
        self.assertEqual(self.run_model(frame)["dataset_hash"], result["dataset_hash"])

    def test_unknown_ohlc_order_uses_stop_first_and_adverse_gap_open(self):
        frame = long_fixture()
        frame.loc[141, ["high", "low"]] = [111., 100.]
        trade = self.run_model(frame)["trades"][0]
        self.assertEqual(trade["exit"], 101.)
        self.assertTrue(trade["ambiguous"])
        self.assertLess(trade["net"], 0)
        frame = long_fixture()
        frame.loc[144:, ["open", "high", "low", "close"]] = [90., 91., 89., 90.]
        trade = self.run_model(frame)["trades"][0]
        self.assertEqual(trade["exit"], 90.)

    def test_future_data_cannot_change_a_completed_trade(self):
        frame = long_fixture()
        baseline = self.run_model(frame)
        future = minutes([50., 60.], frame.iloc[-1]["time"]+pd.Timedelta(minutes=1))
        expanded = pd.concat([frame, future], ignore_index=True)
        self.assertEqual(self.run_model(expanded)["trades"][0], baseline["trades"][0])

    def test_intrabar_modes_require_actual_trade_observations(self):
        for mode in ("REALTIME", "ANTICIPATORY"):
            with self.subTest(mode=mode), self.assertRaises(UnsupportedDataset):
                self.run_model(long_fixture(), config=replace(self.config, entry_mode=mode))

    def test_mixed_contracts_and_invalid_configuration_rejected(self):
        frame = long_fixture()
        frame["contract_id"] = "TEST.CONTRACT"
        frame.loc[1, "contract_id"] = "OTHER.CONTRACT"
        with self.assertRaises(UnsupportedDataset):
            self.run_model(frame)
        with self.assertRaises(ValueError):
            self.run_model(long_fixture(), simulation=replace(self.sim, quantity=5))

    def test_chronological_split_does_not_include_training_entries_in_test(self):
        runs = chronological_splits(long_fixture(), "MNQ", "TEST.CONTRACT", strategy_config=self.config,
                                     simulation=self.sim, training_fraction=.7)
        self.assertEqual(len(runs), 1)
        for trade in runs[0]["out_of_sample"]["trades"]:
            self.assertGreaterEqual(pd.Timestamp(trade["entry_time"]), pd.Timestamp(runs[0]["split_at"]))

    def test_selected_window_keeps_prior_warmup_without_counting_prior_trades(self):
        frame = long_fixture()
        start = frame.iloc[141]["time"]
        result = self.run_model(frame, trade_start=start)
        self.assertEqual(result["start"], start.isoformat())
        self.assertEqual(result["warmup_start"], frame.iloc[0]["time"].isoformat())
        self.assertEqual(len(result["trades"]), 1)
        self.assertGreaterEqual(pd.Timestamp(result["trades"][0]["entry_time"]), start)
        with self.assertRaises(ValueError):
            self.run_model(frame, trade_start=frame.iloc[-1]["time"]+pd.Timedelta(days=1))

    def test_all_six_contract_specs_have_distinct_correct_values(self):
        for symbol, tick, point in (("NQ", .25, 20), ("MNQ", .25, 2), ("ES", .25, 50),
                                    ("MES", .25, 5), ("YM", 1, 5), ("MYM", 1, .5)):
            spec = instrument(symbol)
            self.assertEqual((spec.tick_size, spec.point_value, spec.tick_value), (tick, point, tick*point))

    def test_metrics_use_net_trades_and_preserve_sample_counts(self):
        rows = [dict(net=value, gross=value+1, costs=1, holding_seconds=60, exit_time=f"2026-10-02T00:{i:02d}:00Z")
                for i, value in enumerate((10., -5., -7., 0., 4.))]
        result = statistics(rows, starting_balance=100)
        self.assertEqual((result["trades"], result["wins"], result["losses"], result["breakeven"]), (5, 2, 2, 1))
        self.assertEqual(result["net"], 2.)
        self.assertEqual(result["max_consecutive_losses"], 2)
        self.assertEqual(result["max_drawdown"], 12.)
