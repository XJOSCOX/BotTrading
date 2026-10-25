"""Deterministic acceptance evidence, not strategy profitability evidence."""
import copy
import json
import unittest
from unittest.mock import patch

import pandas as pd
from goxtrade.execution import trade_manager
from goxtrade.execution.profit_policy import ProfitPolicy, comparison_policies
from goxtrade.execution.strategy_manager import evaluate
from goxtrade.execution.trade_analytics import analytics
from goxtrade.research.managed_positions import with_exit_policy
from goxtrade.research.portfolio_backtest import candidates_at
from goxtrade.research.portfolio_forward_paper import empty_portfolio, advance_portfolio
from tests.manager_fixtures import NOW, CONTRACT, candidate, facts, policy
from tests.vwap_fixtures import minutes


def profit_reversals():
    results = []
    for name, settings in comparison_policies().items():
        for peak in (.5, 1., 1.5, 2., 3.):
            for direction, sign in (("LONG", 1), ("SHORT", -1)):
                state = trade_manager.open_trade(trade_id="acceptance", symbol="MNQ", contract_id=CONTRACT,
                    direction=direction, entry=100., quantity=3, stop=100-sign*10, target=100+sign*40,
                    entered_at=NOW, policy=settings, commission_per_side=.5, slippage_ticks=1)
                stops = [state["stop"]]
                for sequence, distance in enumerate((-2.5, peak*10, 0., -12.5), 1):
                    state = trade_manager.observe(state, 100+sign*distance,
                        (pd.Timestamp(NOW)+pd.Timedelta(seconds=sequence)).isoformat(), sequence, CONTRACT)
                    state = trade_manager.simulate_exit(state, state["last_time"])
                    stops.append(state["stop"])
                results.append(dict(policy=name, peak=peak, direction=direction, state=state,
                                    stops=stops, analytics=analytics(state)))
    return results


class SystemAcceptanceTests(unittest.TestCase):
    def setUp(self):
        for name in ("post", "login"):
            mock = patch("goxtrade.execution.projectx_client."+name, side_effect=AssertionError("Broker forbidden"))
            mock.start()
            self.addCleanup(mock.stop)

    def test_decision_matrix_is_explainable_and_deterministic(self):
        variants = [
            ("single", [candidate()], facts(), policy(), 1),
            ("same direction", [candidate(), candidate("reversal", key="b")], facts(), policy(), 1),
            ("opposing", [candidate(), candidate("reversal", "SHORT", key="b")], facts(), policy(), 0),
            ("indices", [candidate(), candidate(symbol="MES", key="b")], facts(), policy(max_positions=3, max_group_positions=3), 2),
            ("none", [], facts(), policy(), 0),
            ("expired", [candidate(expires_at="2026-10-22T14:59:59Z")], facts(), policy(), 0),
            ("budget", [candidate()], facts(), policy(max_trade_risk=1), 0),
            ("closed", [candidate()], facts(session_allowed=False), policy(), 0),
            ("missing", [candidate(history_complete=False)], facts(), policy(), 0),
            ("stale", [candidate(quote_at="2026-10-22T14:59:00Z")], facts(), policy(), 0),
            ("sudden move", [candidate(price=125.)], facts(), policy(), 0),
            ("disconnected", [candidate()], facts(unresolved=True), policy(), 0),
            ("rollover", [candidate()], facts(contracts=(("MNQ", "CON.F.US.MNQ.H27"),)), policy(), 0),
        ]
        for name, rows, state, settings, count in variants:
            with self.subTest(scenario=name):
                decisions = evaluate(rows, state, settings, NOW)
                self.assertEqual(sum(d.selected for d in decisions), count)
                self.assertEqual(len(decisions), len(rows))
                self.assertTrue(all(d.reasons for d in decisions))
                self.assertEqual(decisions, evaluate(copy.deepcopy(rows), copy.deepcopy(state), settings, NOW))

    def test_actual_indicator_detection_through_fill_exit_and_accounting(self):
        history = minutes(start="2026-10-22T22:00Z")
        history.attrs["contract_id"] = CONTRACT
        now = history.iloc[-1].time+pd.Timedelta(minutes=1)
        settings = policy(paper_enabled=True, symbols=("MNQ",), monitoring=("vwap_ema_cross",), participating=("vwap_ema_cross",), requested_quantity=2)
        rows, waits = candidates_at({"MNQ": history}, {"MNQ": 103.}, {"MNQ": CONTRACT}, now,
            settings, account="test", profile="paper", configurations={"vwap_ema_cross": dict(stop_method="fixed")})
        self.assertEqual(len(rows), 1, waits)
        self.assertTrue(rows[0].confirmed)
        rows = with_exit_policy(rows, ProfitPolicy(enabled=True, mode="fixed", target_method="rr", target_r=1))
        state = advance_portfolio(empty_portfolio("test"), rows, [], settings, now, contracts={"MNQ": CONTRACT}, session_allowed=True)
        self.assertEqual(len(state["pending"]), 1)
        self.assertFalse(state["positions"])
        for sequence, price in enumerate((103., 110.), 1):
            when = now+pd.Timedelta(seconds=sequence)
            tick = dict(sequence=sequence, time=when.isoformat(), price=price, symbol="MNQ", contract_id=CONTRACT)
            state = advance_portfolio(json.loads(json.dumps(state)), [], [tick], settings, when,
                contracts={"MNQ": CONTRACT}, session_allowed=True)
        self.assertEqual(len(state["trades"]), 1)
        trade = state["trades"][0]
        self.assertEqual(trade["entry"], 103.25)
        self.assertEqual(trade["exit"], 109.75)
        self.assertEqual(trade["net"], 24.)
        self.assertEqual(state["realized"], trade["net"])
        self.assertFalse(state["positions"] or state["pending"])

    def test_all_profit_policies_reversals_quantities_excursions_and_stops(self):
        results = profit_reversals()
        self.assertEqual(len(results), 100)
        for row in results:
            with self.subTest(policy=row["policy"], peak=row["peak"], direction=row["direction"]):
                state, result = row["state"], row["analytics"]
                sign = state["sign"]
                self.assertEqual(state["remaining"], 0)
                self.assertEqual(sum(fill["quantity"] for fill in state["fills"]), 3)
                self.assertTrue(all((b-a)*sign >= 0 for a, b in zip(row["stops"], row["stops"][1:])))
                self.assertAlmostEqual(result["mfe_points"], row["peak"]*10)
                self.assertGreaterEqual(result["mae_points"], 2.5)
                self.assertAlmostEqual(result["realized_net"], sum(fill["net"] for fill in state["fills"]))
                self.assertAlmostEqual(result["profit_giveback"], max(0., result["maximum_marked_profit"]-result["realized_gross"]))
                self.assertIn("not broker", result["protection_status"])
