from dataclasses import replace
from contextlib import closing
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from goxtrade.research.backtest import SimulationConfig, run_backtest, fill_validation, manage_after_close
from goxtrade.research.forward_paper import advance_paper
from goxtrade.strategies.strategy_catalog import STRATEGIES
from goxtrade.strategies.vwap_ema_config import VwapEmaConfig
from goxtrade.strategies.vwap_ema_cross import evaluate_vwap_ema_cross
from tests.vwap_fixtures import minutes
from tests.test_strategy_backtesting import long_fixture


class ResearchAccountingTests(unittest.TestCase):
    def setUp(self):
        self.config = VwapEmaConfig(stop_method="fixed", management_method="fixed")
        self.sim = SimulationConfig(quantity=2, commission_per_side=.5, slippage_ticks=1)

    def model(self, source=None, sim=None, config=None):
        return run_backtest(source if source is not None else long_fixture(), "MNQ", "TEST.CONTRACT",
                             strategy_config=config or self.config, simulation=sim or self.sim)

    def test_omitted_or_unacknowledged_zero_commission_is_rejected(self):
        for sim in (SimulationConfig(), replace(self.sim, commission_per_side=0.)):
            with self.assertRaises(ValueError):
                self.model(sim=sim)
        self.model(sim=replace(self.sim, commission_per_side=0., zero_cost_sensitivity=True))

    def test_round_trip_costs_and_slippage_are_not_subtracted_twice(self):
        result = self.model()
        trade = result["trades"][0]
        self.assertEqual((trade["entry"], trade["exit"]), (104.25, 109.75))
        self.assertEqual((trade["gross"], trade["costs"], trade["net"]), (22., 2., 20.))
        self.assertEqual(trade["slippage_cost"], 2.)
        self.assertEqual(trade["fill_validation"]["initial_risk_usd"], 13.)
        self.assertAlmostEqual(trade["fill_validation"]["effective_reward_risk"], 5.75/3.25)

    def test_post_slippage_invalid_geometry_rr_and_research_risk_are_counted(self):
        for sim, reason in ((replace(self.sim, slippage_ticks=100), "geometry"),
                            (replace(self.sim, minimum_effective_rr=2.), "effective RR"),
                            (replace(self.sim, max_initial_risk_usd=10.), "initial-risk cap")):
            result = self.model(sim=sim)
            self.assertEqual(result["summary"]["trades"], 0)
            self.assertTrue(any(reason in key for key in result["decisions"]), result["decisions"])

    def test_open_fee_realized_balance_and_unrealized_equity_are_separate(self):
        result = self.model(source=long_fixture().iloc[:142])
        self.assertTrue(result["open_at_end"])
        self.assertEqual(result["summary"]["net"], 0.)
        self.assertEqual(result["accounting"]["closed_trade_net"], 0.)
        self.assertEqual(result["accounting"]["open_entry_commission"], 1.)
        self.assertEqual(result["accounting"]["realized_balance"], 49999.)
        self.assertEqual(result["accounting"]["marked_equity"], 49998.)
        self.assertEqual(result["accounting"]["unrealized_pnl"], -1.)

    def test_bad_price_grid_and_fractional_slippage_fail(self):
        source = long_fixture()
        source.loc[1, "close"] = 101.1
        with self.assertRaises(ValueError):
            self.model(source=source)
        with self.assertRaises(ValueError):
            self.model(sim=replace(self.sim, slippage_ticks=.5))

    def test_projectx_mini_history_cannot_be_silently_priced_as_a_micro(self):
        with self.assertRaisesRegex(ValueError, "instrument"):
            run_backtest(long_fixture(), "MNQ", "CON.F.US.ENQ.Z26", simulation=self.sim)

    def test_monthly_returns_use_central_time_and_realized_net(self):
        from goxtrade.research.metrics import monthly_returns
        rows = [dict(net=10., exit_time="2026-10-01T00:30:00Z"), dict(net=-5., exit_time="2026-10-01T06:00:00Z")]
        values = monthly_returns(rows, 100.)
        self.assertEqual(list(values), ["2026-09", "2026-10"])
        self.assertEqual(values["2026-09"]["closed_trade_return_percent"], 10.)
        self.assertEqual(values["2026-10"]["starting_balance"], 110.)
        self.assertAlmostEqual(values["2026-10"]["closed_trade_return_percent"], -5/110*100)

    def test_trailing_never_widens_and_break_even_requires_trigger(self):
        active = dict(signal="LONG", entry=100., initial_stop=95., stop=95., exit_mode="trailing", trail_start_r=1., trail_ticks=4, tick_size=.25)
        manage_after_close(active, dict(close=106.), pd.DataFrame(), pd.Timestamp("2026-10-01T15:00Z"))
        self.assertEqual(active["stop"], 105.)
        manage_after_close(active, dict(close=101.), pd.DataFrame(), pd.Timestamp("2026-10-01T15:01Z"))
        self.assertEqual(active["stop"], 105.)
        active.update(stop=95., exit_mode="breakeven", breakeven_r=1.)
        manage_after_close(active, dict(close=104.), pd.DataFrame(), pd.Timestamp("2026-10-01T15:02Z"))
        self.assertEqual(active["stop"], 95.)
        manage_after_close(active, dict(close=105.), pd.DataFrame(), pd.Timestamp("2026-10-01T15:03Z"))
        self.assertEqual(active["stop"], 100.)

    def test_repeated_simulations_are_identical_and_do_not_read_broker(self):
        with patch("goxtrade.execution.projectx_client.post", side_effect=AssertionError("Broker calls forbidden")) as broker:
            self.assertEqual(self.model(), self.model())
            broker.assert_not_called()

    def test_all_six_strategy_adapters_run_without_changing_legacy_rules(self):
        source = minutes([100.]*320)
        for strategy in STRATEGIES:
            with self.subTest(strategy=strategy):
                result = run_backtest(source, "MNQ", "TEST.CONTRACT", strategy=strategy, simulation=self.sim,
                                       strategy_config=self.config if strategy == "VWAP EMA Cross" else None)
                self.assertEqual(result["strategy"], strategy)
                self.assertEqual(result["summary"]["trades"], 0)


class ForwardSafetyTests(unittest.TestCase):
    def setUp(self):
        calendar=patch("goxtrade.market.calendar_guard.restriction",return_value=dict(allow_entry=True,flatten=False))
        calendar.start();self.addCleanup(calendar.stop)
        self.minutes = minutes()
        self.now = self.minutes.iloc[-1]["time"]+pd.Timedelta(minutes=1)
        self.config = VwapEmaConfig(paper_enabled=True, paper_zero_cost_sensitivity=True, stop_method="fixed", management_method="fixed", paper_slippage_ticks=1.)
        self.signal = evaluate_vwap_ema_cross(self.minutes, 103., self.now, self.config, historical=True)[0]
        self.signal["detection_sequence"] = 1

    def advance(self, state, candidate=None, ticks=(), config=None, contract="TEST.CONTRACT"):
        return advance_paper(state, candidate or {}, ticks, self.minutes, "MNQ=F", contract, config or self.config, self.now+pd.Timedelta(seconds=2))

    def tick(self, price=103., received=None):
        return dict(id=2, price=price, event_time=(self.now+pd.Timedelta(seconds=1)).isoformat(), received_at=(received or self.now+pd.Timedelta(seconds=1)).isoformat())

    def test_paper_zero_fees_require_acknowledgement_but_do_not_destroy_existing_state(self):
        state, _ = self.advance(dict(cursor=1), self.signal, config=replace(self.config, paper_zero_cost_sensitivity=False))
        self.assertIsNone(state["pending"])
        self.assertIn("commission", state["message"])

    def test_pending_contract_rollover_cannot_fill_old_setup_on_new_contract(self):
        state, _ = self.advance(dict(cursor=1), self.signal)
        state, trades = self.advance(state, ticks=[self.tick()], contract="OTHER.CONTRACT")
        self.assertIsNone(state["active"])
        self.assertIsNone(state["pending"])
        self.assertEqual(trades, [])

    def test_fill_slippage_crossing_levels_is_classified_not_optimistically_skipped(self):
        config = replace(self.config, paper_slippage_ticks=100.)
        signal = {**self.signal, "config_snapshot": config.to_dict()}
        state, _ = self.advance(dict(cursor=1), signal, config=config)
        state, trades = self.advance(state, ticks=[self.tick()], config=config)
        self.assertIsNone(state["active"])
        self.assertEqual(len(trades), 1)
        self.assertFalse(trades[0]["fill_validation"]["valid"])
        self.assertLess(trades[0]["net"], 0.)

    def test_stale_micro_receipt_cannot_fill_pending_entry(self):
        state, _ = self.advance(dict(cursor=1), self.signal)
        state, trades = self.advance(state, ticks=[self.tick(received=self.now-pd.Timedelta(seconds=30))])
        self.assertIsNone(state["active"])
        self.assertEqual(trades, [])

    def test_mode_changes_do_not_replay_consumed_paper_crossover(self):
        state, _ = self.advance(dict(cursor=1), self.signal)
        state, _ = self.advance(state, ticks=[self.tick()])
        stop = {**self.tick(price=99.), "id": 3}
        state, trades = self.advance(state, ticks=[stop])
        self.assertEqual(len(trades), 1)
        changed = dict(self.signal, entry_mode="REALTIME", unique_setup_id="b"*64)
        state, _ = self.advance(state, candidate=changed)
        self.assertIsNone(state["pending"])

    def test_wrapper_persists_legacy_consumption_migration_without_new_ticks(self):
        from goxtrade.data import live_store
        from goxtrade.research.forward_paper import forward_once
        from goxtrade.bot import strategy_events
        from goxtrade.strategies.strategy_catalog import crossover_key
        event = dict(self.signal, symbol="NQ=F", source_contract="REFERENCE", session_id="session")
        with tempfile.TemporaryDirectory() as directory, patch.object(live_store, "DB_PATH", Path(directory)/"paper.db"), \
                patch("goxtrade.research.forward_paper.contract_for_symbol", return_value="TEST.CONTRACT"):
            strategy_events.persist("prior", {}, {}, event)
            with closing(live_store.connect()) as conn:
                conn.execute("CREATE TABLE strategy_paper_states(identity TEXT PRIMARY KEY,record TEXT NOT NULL)")
                conn.execute("INSERT INTO strategy_paper_states VALUES (?,?)", ("vwap_ema_cross|MNQ=F", json.dumps(dict(contract_id="TEST.CONTRACT", cursor=0, active=None, pending=None, seen_events=[event["unique_setup_id"]]))))
                conn.commit()
            forward_once("NQ=F", {}, replace(self.config, paper_enabled=False), self.now)
            with closing(live_store.connect()) as conn:
                state = json.loads(conn.execute("SELECT record FROM strategy_paper_states").fetchone()[0])
            self.assertEqual(state["consumption_version"], 2)
            self.assertIn(crossover_key(event), state["seen_events"])
            self.assertFalse(state.get("consumption_unverified"))
