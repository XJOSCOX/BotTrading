from dataclasses import replace
from contextlib import closing, ExitStack
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd
from goxtrade.research.portfolio_forward_paper import empty_portfolio, advance_portfolio, portfolio_summary
from tests.manager_fixtures import NOW, CONTRACT, candidate, policy


class PortfolioPaperTests(unittest.TestCase):
    def advance(self, state, candidates=(), ticks=(), now=NOW, settings=None):
        return advance_portfolio(state, candidates, ticks, settings or policy(paper_enabled=True), now,
            contracts={"MNQ": CONTRACT}, session_allowed=True, session_reason="Fixture session")

    def tick(self, seq, when, price=100):
        return dict(sequence=seq, time=when, price=price, symbol="MNQ", contract_id=CONTRACT)

    def test_off_by_default_and_no_synthetic_fill(self):
        state = empty_portfolio("test")
        row = candidate(profile="paper")
        result = self.advance(state, [row], settings=policy())
        self.assertFalse(result["pending"])
        result = self.advance(state, [row])
        self.assertEqual(len(result["pending"]), 1)
        self.assertFalse(result["positions"])
        # Same-timestamp trade cannot be retroactively used after selection.
        result = self.advance(result, ticks=[self.tick(1, NOW)])
        self.assertFalse(result["positions"])

    def test_next_tick_fill_costs_stop_and_restart_dedupe(self):
        row = candidate(profile="paper")
        state = self.advance(empty_portfolio("test"), [row])
        state = self.advance(state, ticks=[self.tick(1, "2026-10-22T15:00:01+00:00")], now="2026-10-22T15:00:01+00:00")
        self.assertEqual(state["positions"][0]["exposure"]["entry"], 100.25)
        state = self.advance(state, ticks=[self.tick(2, "2026-10-22T15:00:02+00:00", 89)], now="2026-10-22T15:00:02+00:00")
        self.assertEqual(state["trades"][0]["exit"], 88.75)
        self.assertEqual(state["trades"][0]["net"], -24.)
        self.assertEqual(portfolio_summary(state)["metrics"]["max_drawdown"], 24.)
        self.assertFalse(self.advance(state, [row], now="2026-10-22T15:00:02+00:00")["pending"])
        with self.assertRaises(ValueError):
            self.advance(state, ticks=[self.tick(2, "2026-10-22T15:00:02+00:00", 89)], now="2026-10-22T15:00:02+00:00")

    def test_fill_revalidation_never_tightens_stop(self):
        state = self.advance(empty_portfolio("test"), [candidate(profile="paper")])
        state = self.advance(state, ticks=[self.tick(1, "2026-10-22T15:00:01+00:00", 125)], now="2026-10-22T15:00:01+00:00")
        self.assertFalse(state["positions"])
        self.assertIn("geometry", state["decisions"][-1]["reasons"][0])

    def test_disabled_new_entries_keep_exit_management(self):
        state = self.advance(empty_portfolio("test"), [candidate(profile="paper")])
        state = self.advance(state, ticks=[self.tick(1, "2026-10-22T15:00:01+00:00")], now="2026-10-22T15:00:01+00:00")
        state = self.advance(state, ticks=[self.tick(2, "2026-10-22T15:00:02+00:00", 125)], now="2026-10-22T15:00:02+00:00", settings=policy(paper_enabled=False))
        self.assertEqual(len(state["trades"]), 1)

    def test_conflicting_candidates_no_paper_positions(self):
        rows = [candidate(profile="paper"), candidate("reversal", "SHORT", key="b", profile="paper")]
        state = self.advance(empty_portfolio("test"), rows)
        self.assertFalse(state["pending"])
        self.assertEqual(portfolio_summary(state)["conflict_rate"], 1.)

    def test_pause_or_stricter_policy_cancels_pending_not_existing_stops(self):
        for settings in (policy(paper_enabled=False), policy(paper_enabled=True, max_trade_risk=5), policy(paper_enabled=True, participating=())):
            state = self.advance(empty_portfolio("test"), [candidate(profile="paper")])
            state = self.advance(state, ticks=[self.tick(1, "2026-10-22T15:00:01+00:00")], now="2026-10-22T15:00:01+00:00", settings=settings)
            self.assertFalse(state["positions"])
            self.assertFalse(state["pending"])

    def test_pending_expiry_is_audited(self):
        state = self.advance(empty_portfolio("test"), [candidate(profile="paper")])
        state = self.advance(state, now="2026-10-22T15:03:00+00:00")
        self.assertFalse(state["pending"])
        self.assertEqual(state["decisions"][-1]["eligibility"], "EXPIRED")


class PortfolioPaperPersistenceTests(unittest.TestCase):
    def setUp(self):
        from goxtrade.data import live_store
        from goxtrade.execution import manager_service
        from goxtrade.execution.signal_reservations import initialize
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch.object(live_store, "DB_PATH", Path(directory)/"paper.db"))
        self.stack.enter_context(patch("goxtrade.execution.contracts.contract_for_symbol", return_value=CONTRACT))
        self.stack.enter_context(patch("goxtrade.data.strategy_history.load_strategy_minutes", return_value=pd.DataFrame(columns=["time"])))
        self.stack.enter_context(patch.object(manager_service, "shared_strategy_configs", return_value={}))
        self.settings = policy(paper_enabled=True, symbols=("MNQ",))
        manager_service.save_policy(self.settings.to_dict())
        old = advance_portfolio(empty_portfolio("test"), [candidate(profile="paper")], [], self.settings, NOW,
            contracts={"MNQ": CONTRACT}, session_allowed=True, session_reason="Fixture open")
        old["last_poll_at"] = NOW
        with closing(live_store.connect()) as conn:
            initialize(conn)
            conn.execute("INSERT INTO manager_simulation VALUES ('portfolio-paper','portfolio_forward_paper',?)", (json.dumps(dict(kind="portfolio_forward_paper", state=old)),))
            conn.commit()

    def tick(self, time, price, received=None):
        from goxtrade.data import live_store
        with closing(live_store.connect()) as conn:
            conn.execute("INSERT INTO live_ticks(symbol,contract_id,event_type,price,event_time,received_at) VALUES (?,?, 'trade',?,?,?)",
                         ("MNQ=F", CONTRACT, price, time, received or time))
            conn.commit()

    def test_real_observation_path_restarts_without_duplicate_fills(self):
        from goxtrade.execution import manager_service
        self.tick("2026-10-22T15:00:01+00:00", 100.)
        self.tick("2026-10-22T15:00:02+00:00", 125.)
        result = manager_service.paper_once("2026-10-22T15:00:02+00:00")
        self.assertEqual(len(result["state"]["trades"]), 1)
        again = manager_service.paper_once("2026-10-22T15:00:02+00:00")
        self.assertEqual(len(again["state"]["trades"]), 1)
        self.tick("2026-10-22T15:00:01+00:00", 85., received="2026-10-22T15:00:03+00:00")
        late = manager_service.paper_once("2026-10-22T15:00:03+00:00")
        self.assertEqual(len(late["state"]["trades"]), 1)
        self.assertTrue(late["state"]["data_rejections"])

    def test_conflicting_writer_is_not_overwritten(self):
        from goxtrade.execution import manager_service
        from goxtrade.data import live_store
        def race(*args, **kwargs):
            with closing(live_store.connect()) as conn:
                conn.execute("UPDATE manager_simulation SET record=record||' ' WHERE id='portfolio-paper'")
                conn.commit()
            return [], []
        with patch("goxtrade.research.portfolio_backtest.candidates_at", side_effect=race):
            result = manager_service.paper_once("2026-10-22T15:00:01+00:00")
        self.assertIn("concurrently", result["message"])
