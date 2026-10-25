from dataclasses import replace
from unittest.mock import patch
import unittest
import pandas as pd

from goxtrade.research.portfolio_backtest import run_portfolio_backtest, candidates_at, walk_forward
from tests.manager_fixtures import NOW, CONTRACT, candidate, policy


def minutes(periods=6):
    times = pd.date_range(NOW, periods=periods, freq="min")
    frame = pd.DataFrame(dict(time=times, open=100., high=101., low=99., close=100., volume=10., complete=True))
    frame.attrs["contract_id"] = CONTRACT
    return frame


def signals(known, prices, contracts, now, settings, *, account, profile):
    for frame in known.values():
        assert frame.empty or frame["time"].max() < now
    if now == pd.Timestamp(NOW)+pd.Timedelta(minutes=1):
        rows = [candidate("crt", symbol=symbol, key=symbol, account_id=account, profile=profile,
            created_at=now.isoformat(), confirmed_at=now.isoformat(), quote_at=now.isoformat(),
            expires_at=(now+pd.Timedelta(minutes=2)).isoformat()) for symbol in prices]
        return rows, []
    return [], []


class PortfolioBacktestTests(unittest.TestCase):
    def test_chronological_competition_shared_risk_not_summed(self):
        nq, es = minutes(), minutes()
        es.attrs["contract_id"] = "CON.F.US.MES.Z26"
        result = run_portfolio_backtest([("MNQ", CONTRACT, nq), ("MES", es.attrs["contract_id"], es)], policy(), candidate_source=signals)
        self.assertEqual(len(result["state"]["positions"]), 1)
        self.assertEqual(result["state"]["positions"][0]["filled_at"], "2026-10-22T15:02:00+00:00")
        self.assertEqual(result["broker_checks"], "NOT_PERFORMED")
        self.assertTrue(any(row["eligibility"] == "RISK_BLOCKED" for row in result["state"]["decisions"]))

    def test_ambiguous_bar_stop_first_costs_and_drawdown(self):
        frame = minutes()
        frame.loc[2, ["low", "high"]] = [85., 125.]
        result = run_portfolio_backtest([("MNQ", CONTRACT, frame)], policy(), candidate_source=signals)
        trade = result["state"]["trades"][0]
        self.assertTrue(trade["ambiguous"])
        self.assertEqual(trade["exit"], 89.75)
        self.assertEqual(trade["net"], -22.)
        self.assertGreaterEqual(result["summary"]["metrics"]["max_drawdown"], 22.)

    def test_future_mutation_does_not_change_past_decisions(self):
        base = minutes()
        changed = base.copy()
        changed.loc[5, "high"] = 500.
        a = run_portfolio_backtest([("MNQ", CONTRACT, base)], policy(), candidate_source=signals)
        b = run_portfolio_backtest([("MNQ", CONTRACT, changed)], policy(), candidate_source=signals)
        self.assertEqual(a["state"]["decisions"], b["state"]["decisions"])
        self.assertNotEqual(a["datasets"], b["datasets"])

    def test_rollover_partial_and_costs_rejected(self):
        frame = minutes()
        frame.loc[2, "complete"] = False
        with self.assertRaises(ValueError):
            run_portfolio_backtest([("MNQ", CONTRACT, frame)], policy(), candidate_source=signals)
        with self.assertRaises(ValueError):
            run_portfolio_backtest([("MNQ", "CON.F.US.MES.Z26", minutes())], policy())
        with self.assertRaises(ValueError):
            run_portfolio_backtest([("MNQ", CONTRACT, minutes())], policy(commission_per_side=None))

    def test_gap_closes_at_next_observed_open(self):
        frame = minutes(10).drop(index=3).reset_index(drop=True)
        result = run_portfolio_backtest([("MNQ", CONTRACT, frame)], policy(), candidate_source=signals)
        self.assertIn("Data gap", result["state"]["trades"][0]["reason"])
        self.assertTrue(result["state"]["trades"][0]["ambiguous"])

    def test_actual_adapters_empty_history_no_fabricated_trades(self):
        result = run_portfolio_backtest([("MNQ", CONTRACT, minutes())], policy())
        self.assertFalse(result["state"]["trades"])
        self.assertTrue(result["state"]["data_rejections"])

    def test_walk_forward_fixed_policy_warmup_and_small_dataset(self):
        with self.assertRaises(ValueError):
            walk_forward([("MNQ", CONTRACT, minutes())], policy())
        limited = policy(participating=())
        result = walk_forward([("MNQ", CONTRACT, minutes(90))], limited)
        self.assertEqual(len(result), 2)
        self.assertFalse(result[0]["policy_fitted"])
        self.assertLess(result[0]["test_end"], result[1]["test_start"])

    def test_all_seven_real_adapter_routes_normalize_without_broker_calls(self):
        history = minutes(120)
        history["time"] = pd.date_range(pd.Timestamp(NOW)-pd.Timedelta(minutes=120), periods=120, freq="min")
        raw = dict(signal="LONG", entry=100., stop=90., target=120., unique_setup_id="fixture-setup",
                   signal_minutes=15, entry_mode="CONFIRMED", exit_mode="fixed", setup_time=(pd.Timestamp(NOW)-pd.Timedelta(minutes=15)).isoformat())
        with patch("goxtrade.research.portfolio_backtest.legacy_candidate", return_value=raw) as legacy, \
             patch("goxtrade.strategies.entry_confirmation.evaluate", return_value=dict(state="Confirmed")), \
             patch("goxtrade.strategies.vwap_ema_cross.evaluate_vwap_ema_cross", return_value=({**raw, "signal_minutes": 3}, pd.DataFrame(), {})) as vwap, \
             patch("goxtrade.strategies.previous_day_box.evaluate_previous_day_box", return_value=(raw, pd.DataFrame())) as box:
            rows, _ = candidates_at({"MNQ": history}, {"MNQ": 100.}, {"MNQ": CONTRACT}, pd.Timestamp(NOW), policy(), account="test", profile="research")
        self.assertEqual(len(rows), 7)
        self.assertEqual(legacy.call_count, 5)
        vwap.assert_called_once()
        box.assert_called_once()
        self.assertTrue(all(row.confirmed for row in rows))

    def test_required_history_verification_cannot_be_ignored(self):
        history = minutes()
        history.loc[0, "complete"] = False
        rows, waits = candidates_at({"MNQ": history}, {"MNQ": 100.}, {"MNQ": CONTRACT}, pd.Timestamp(NOW)+pd.Timedelta(minutes=6), policy(), account="test", profile="paper")
        self.assertFalse(rows)
        self.assertEqual(len(waits), 7)
