from contextlib import closing
from dataclasses import replace
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd

from goxtrade.execution.profit_policy import ProfitPolicy
from goxtrade.execution import trade_manager as manager
from goxtrade.research.portfolio_backtest import run_portfolio_backtest
from goxtrade.research.exit_policy_comparison import compare_exits, chronological_exit_folds
from tests.manager_fixtures import NOW, CONTRACT, candidate, policy
from tests.test_trade_management import trade, tick
from tests.test_portfolio_backtest import minutes, signals


class TradeManagementIntegrationTests(unittest.TestCase):
    def test_partial_bar_does_not_invent_trail_before_intrabar_reversal(self):
        frame = minutes(3)
        frame.loc[2, ["high", "low", "close"]] = [112., 99., 105.]
        result = run_portfolio_backtest([("MNQ", CONTRACT, frame)], policy(requested_quantity=2), candidate_source=signals,
            profit_policy=ProfitPolicy(enabled=True, mode="partial", partial_targets=((1., 1),), trail_start_r=1., trail_ticks=8))
        self.assertEqual(len(result["state"]["positions"]), 1)
        managed = result["state"]["positions"][0]["trade_management"]
        self.assertEqual(managed["remaining"], 1)
        self.assertIsNone(managed["pending_exit"])
        self.assertEqual(len(result["state"]["trades"]), 0)

    def test_portfolio_partial_episode_costs_and_risk_quantity(self):
        frame = minutes(6)
        frame.loc[2, ["high","close"]] = [111., 110.]
        frame.loc[3, ["open","high","low","close"]] = [110., 120., 109., 119.]
        frame.loc[4, ["open","high","low","close"]] = [119., 120., 100., 101.]
        result = run_portfolio_backtest([("MNQ",CONTRACT,frame)], policy(requested_quantity=2), candidate_source=signals,
            profit_policy=ProfitPolicy(enabled=True, mode="partial", partial_targets=((1.,1),), trail_start_r=1., trail_ticks=8))
        self.assertEqual(len(result["state"]["trades"]), 1)
        episode = result["state"]["trades"][0]
        self.assertEqual(episode["quantity"], 2)
        self.assertEqual(len(episode["partial_fills"]), 2)
        self.assertEqual(episode["costs"], 2.)
        self.assertAlmostEqual(episode["net"], sum(fill["net"] for fill in episode["partial_fills"]))
        self.assertEqual(result["summary"]["metrics"]["trades"], 1)

    def test_baseline_keeps_legacy_positions_without_migration(self):
        result = run_portfolio_backtest([("MNQ",CONTRACT,minutes())], policy(), candidate_source=signals)
        self.assertNotIn("trade_management", result["state"]["positions"][0])
        result = run_portfolio_backtest([("MNQ",CONTRACT,minutes())], policy(), candidate_source=signals, profit_policy=ProfitPolicy())
        self.assertNotIn("trade_management", result["state"]["positions"][0])

    def test_exact_candidate_tape_and_no_false_performance_claim(self):
        frame = minutes(6)
        frame.loc[3, "high"] = 125.
        result = compare_exits([("MNQ",CONTRACT,frame)], policy(), candidate_source=signals)
        self.assertEqual(len(result["policies"]), 10)
        self.assertTrue(result["candidate_tape_hash"])
        self.assertEqual(result["broker_checks"], "NOT_PERFORMED")
        self.assertEqual(result["candidate_events"], 1)
        self.assertEqual(result["policies"]["fixed_1.0R"]["summary"]["metrics"]["trades"], 1)

    def test_atr_structure_and_future_candle_filter(self):
        frame = minutes(90)
        frame["time"] = pd.date_range(pd.Timestamp(NOW)-pd.Timedelta(minutes=90), periods=90, freq="min")
        state = trade(mode="trailing", trailing_method="atr", trail_start_r=1.)
        state = tick(state, 120, 1, minutes=frame.to_dict("records"))
        self.assertGreater(state["stop"], 90.)
        before = state["stop"]
        future = dict(time="2026-10-22T16:00:00Z", high=1000., low=1., close=100.)
        state = tick(state, 121, 2, minutes=frame.to_dict("records")+[future])
        self.assertGreaterEqual(state["stop"], before)
        with self.assertRaises(ValueError):
            manager.completed_features(frame.to_dict("records")+[frame.iloc[0].to_dict()], NOW, ProfitPolicy(), NOW)

    def test_completed_structure_uses_own_frozen_interval(self):
        base = dict(signal="LONG", entry=100., stop=90., initial_stop=90., target=130., exit_mode="structure-v1",
                    management_minutes=5, structure_lookback=3, break_confirmations=2, trail_start_r=1.5, trail_buffer=1.)
        state = manager.open_trade(trade_id="s", symbol="MNQ", contract_id=CONTRACT, direction="LONG", entry=100., quantity=1,
            stop=90., target=130., entered_at=NOW, policy=ProfitPolicy(enabled=True, mode="baseline"),
            commission_per_side=.5, slippage_ticks=1, baseline=base)
        bars = minutes(40)
        bars["low"], bars["high"], bars["close"] = 95., 110., 105.
        bars.loc[20:24,"close"] = 94.
        bars.loc[20:24,"low"] = 93.
        bars.loc[25:29,"close"] = 92.
        bars.loc[25:29,"low"] = 91.
        state = manager.observe(state, 101., "2026-10-22T15:30:00Z", 1, CONTRACT, minutes=bars.to_dict("records"))
        self.assertEqual(state["pending_exit"]["reason"], "Structure break")

    def test_partial_roundtrip_restores_engine_and_disabled_entries_manage(self):
        from goxtrade.research.portfolio_forward_paper import empty_portfolio, advance_portfolio
        from goxtrade.research.managed_positions import with_exit_policy
        settings = policy(requested_quantity=2, paper_enabled=True)
        row = candidate(account_id="test", profile="paper")
        rows = with_exit_policy([row], ProfitPolicy(enabled=True, mode="partial", partial_targets=((1.,1),)))
        def advance(state, rows, observations, time, settings=settings):
            return advance_portfolio(state, rows, observations, settings, time, contracts={"MNQ":CONTRACT}, session_allowed=True)
        state = advance(empty_portfolio("test"), rows, [], NOW)
        observation = lambda seq,sec,price:dict(sequence=seq,time=f"2026-10-22T15:00:{sec:02d}Z",price=price,symbol="MNQ",contract_id=CONTRACT)
        state = advance(state, [], [observation(1,1,100.)], "2026-10-22T15:00:01Z")
        state = advance(state, [], [observation(2,2,111.)], "2026-10-22T15:00:02Z")
        self.assertEqual(state["positions"][0]["exposure"]["quantity"], 1)
        state = json.loads(json.dumps(state))
        state = advance(state, [], [observation(3,3,89.)], "2026-10-22T15:00:03Z", settings=replace(settings,paper_enabled=False))
        self.assertFalse(state["positions"])
        self.assertEqual(len(state["trades"]),1)

    def test_single_strategy_forward_uses_same_engine(self):
        from goxtrade.research.forward_paper import advance_paper
        from goxtrade.strategies.vwap_ema_config import VwapEmaConfig
        config = VwapEmaConfig(paper_enabled=False, paper_commission_per_side=.5)
        active = dict(unique_setup_id="entry", signal="LONG", entry=100., stop=90., initial_stop=90., target=130.,
            entry_time=NOW, management_started_at=NOW, contract_id=CONTRACT, quantity=2, detection_sequence=1, entry_sequence=2,
            config_snapshot=config.to_dict(), exit_mode="fixed", signal_minutes=3, session="fixture",
            profit_policy_snapshot=ProfitPolicy(enabled=True, mode="fixed", target_method="rr", target_r=1).to_dict())
        old = dict(active=active, cursor=2, contract_id=CONTRACT)
        tick = dict(id=3,price=111.,event_time="2026-10-22T15:00:01Z",received_at="2026-10-22T15:00:01Z")
        state, trades = advance_paper(old, {}, [tick], minutes(), "MNQ=F", CONTRACT, config, pd.Timestamp("2026-10-22T15:00:01Z"))
        self.assertIsNone(state["active"])
        self.assertEqual(len(trades),1)
        self.assertIn("management_analytics",trades[0])

    def test_folds_do_not_fit_priorities(self):
        with self.assertRaises(ValueError):
            chronological_exit_folds([("MNQ",CONTRACT,minutes())], policy())
