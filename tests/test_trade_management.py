from dataclasses import replace
import json
import unittest

from goxtrade.execution.profit_policy import ProfitPolicy, comparison_policies
from goxtrade.execution import trade_manager as manager
from goxtrade.execution.trade_analytics import analytics
from tests.manager_fixtures import NOW, CONTRACT


def trade(direction="LONG", quantity=2, **policy):
    return manager.open_trade(trade_id="fixture", symbol="MNQ", contract_id=CONTRACT, direction=direction,
        entry=100., quantity=quantity, stop=90. if direction == "LONG" else 110., target=130. if direction == "LONG" else 70.,
        entered_at=NOW, policy=ProfitPolicy(enabled=True, **policy), commission_per_side=.5, slippage_ticks=1,
        strategy="CRT", session="fixture")


def tick(state, price, second, **kwargs):
    return manager.observe(state, price, f"2026-10-22T15:00:{second:02d}+00:00", second, CONTRACT, **kwargs)


class TradeManagementTests(unittest.TestCase):
    def test_fixed_targets_all_methods_and_directions(self):
        for direction in ("LONG", "SHORT"):
            for method, distance in (("rr", 20), ("ticks", 5), ("points", 10), ("strategy", 30)):
                with self.subTest(direction=direction, method=method):
                    state = trade(direction, mode="fixed", target_method=method)
                    self.assertEqual(abs(state["target"]-100), distance)
                    state = tick(state, state["target"], 1)
                    self.assertEqual(state["pending_exit"]["quantity"], 2)
                    state = manager.simulate_exit(state, state["last_time"])
                    self.assertEqual(state["remaining"], 0)

    def test_breakeven_monotonic_and_cost_aware(self):
        for direction, price in (("LONG", 110), ("SHORT", 90)):
            state = tick(trade(direction, mode="breakeven", break_even_cover_costs=True), price, 1)
            self.assertEqual(state["stop"], 100.5 if direction == "LONG" else 99.5)
            stop = state["stop"]
            state = tick(state, 105 if direction == "LONG" else 95, 2)
            self.assertEqual(state["stop"], stop)

    def test_original_target_and_tick_grid_preserved(self):
        state = trade(mode="fixed", target_method="rr", target_r=1)
        self.assertEqual(state["initial_target"], 130.)
        self.assertEqual(state["target"], 110.)
        with self.assertRaises(ValueError):
            manager.open_trade(trade_id="bad", symbol="MNQ", contract_id=CONTRACT, direction="LONG",
                entry=100., quantity=2, stop=90.1, target=130., entered_at=NOW,
                policy=ProfitPolicy(), commission_per_side=.5, slippage_ticks=1)

    def test_favorable_extreme_trail_never_loosens(self):
        state = tick(trade(mode="trailing", trail_ticks=8, trail_start_r=1), 112, 1)
        self.assertEqual(state["stop"], 110)
        state = tick(state, 111, 2)
        self.assertEqual(state["stop"], 110)
        state = tick(state, 109, 3)
        self.assertEqual(state["pending_exit"]["reason"], "Protective stop")

    def test_profit_lock_after_milestone(self):
        state = tick(trade(mode="profit_lock"), 120, 1)
        self.assertEqual(state["stop"], 110)
        state = tick(state, 115, 2)
        self.assertEqual(state["stop"], 110)

    def test_partial_whole_quantities_and_rejected_fill(self):
        state = tick(trade(mode="partial", partial_targets=((1., 1), (2., 1)), quantity=3), 110, 1)
        intent = state["pending_exit"]
        with self.assertRaises(ValueError):
            manager.reconcile_fill(state, intent_id=intent["id"], fill_id="bad", quantity=2, price=110, when=state["last_time"])
        state = manager.simulate_exit(state, state["last_time"])
        self.assertEqual(state["remaining"], 2)
        state = tick(state, 120, 2)
        state = manager.simulate_exit(state, state["last_time"])
        self.assertEqual(state["remaining"], 1)
        single = tick(trade(mode="partial", partial_targets=((1., 1),), quantity=1), 110, 1)
        self.assertIsNone(single["pending_exit"])

    def test_partial_fill_and_duplicate_exit_recovery(self):
        state = tick(trade(mode="fixed", target_method="rr", target_r=1), 110, 1)
        intent = state["pending_exit"]["id"]
        state = manager.reconcile_fill(state, intent_id=intent, fill_id="a", quantity=1, price=110, when=state["last_time"])
        self.assertEqual(state["remaining"], 1)
        self.assertEqual(state["pending_exit"]["state"], "INTENT")
        self.assertEqual(manager.reconcile_fill(state, intent_id=intent, fill_id="a", quantity=1, price=110, when=state["last_time"]), state)
        restored = json.loads(json.dumps(state))
        restored = manager.reconcile_fill(restored, intent_id=intent, fill_id="b", quantity=1, price=109.75, when=state["last_time"])
        self.assertEqual(restored["remaining"], 0)
        self.assertEqual(len(restored["fills"]), 2)

    def test_mfe_mae_and_giveback_real_costs(self):
        state = tick(trade(mode="baseline"), 120, 1)
        state = tick(state, 95, 2)
        state = tick(state, 89, 3)
        state = manager.simulate_exit(state, state["last_time"])
        result = analytics(state)
        self.assertEqual(result["mfe_dollars"], 80.)
        self.assertEqual(result["mae_dollars"], 44.)
        self.assertGreater(result["profit_giveback"], 80.)
        self.assertIn("Reached 2R then closed negative", result["diagnostic_categories"])
        self.assertEqual(manager.observe(state, 500, "2026-10-22T15:01:00Z", 100, CONTRACT), state)

    def test_stale_wrong_contract_future_and_policy_tamper(self):
        state = trade()
        for args in ((120, "2026-10-22T15:00:01Z", 1, "wrong"), (120, "2026-10-22T14:59:00Z", 1, CONTRACT)):
            current = manager.observe(state, *args)
            self.assertEqual(current["mfe_points"], 0)
        stale = tick(state, 120, 1, observed_at="2026-10-22T15:01:00Z")
        self.assertIsNotNone(stale["blocked_reason"])
        state["policy"]["mode"] = "fixed"
        with self.assertRaises(ValueError):
            tick(state, 110, 1)

    def test_settings_validation_and_prespecified_variants(self):
        self.assertEqual(len(comparison_policies()), 10)
        for value in (dict(enabled="yes"), dict(retain_fraction=1), dict(partial_targets=((1., .5),)), dict(management_minutes=1), dict(extra=True)):
            with self.assertRaises((ValueError, TypeError)):
                ProfitPolicy.from_dict(value)

    def test_strategy_exit_knobs_are_preserved(self):
        from goxtrade.execution.trade_candidate import adapt_alert
        raw = dict(strategy_id="crt", signal="LONG", entry=100, stop=90, target=130, unique_setup_id="setup", detected_at=NOW,
                   exit_mode="structure-v1", management_minutes=5, trail_buffer=4., break_confirmations=3)
        candidate = adapt_alert(raw, account_id="fixture", profile="paper", symbol="MNQ", contract_id=CONTRACT, price=100,
                               quote_at=NOW, confirmed_at=NOW, expires_at="2026-10-22T15:02:00Z", confirmed=True,
                               history_complete=True, execution_eligible=True, session="fixture")
        frozen = json.loads(candidate.risk_json)
        self.assertEqual(frozen["trail_buffer"], 4.)
        self.assertEqual(frozen["break_confirmations"], 3)
