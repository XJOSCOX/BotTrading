import inspect
import unittest
from unittest.mock import patch

from goxtrade.execution import strategy_manager
from goxtrade.execution.strategy_manager import evaluate
from goxtrade.research.portfolio_backtest import session_facts
from tests.manager_fixtures import NOW, candidate, facts, policy
import pandas as pd


class ManagerSafetyTests(unittest.TestCase):
    def test_broker_scope_never_authorizes_even_armed(self):
        for profile in ("practice", "leader"):
            row = candidate(profile=profile)
            result = evaluate([row], facts(profile=profile, reconciled=True, armed=True), policy(), NOW, scope="broker")[0]
            self.assertEqual(result.eligibility, "EXECUTION_DISABLED")
            self.assertFalse(result.selected)

    def test_emergency_pause_disconnect_unowned_uncertainty(self):
        for state in (facts(paused=True), facts(emergency=True), facts(unresolved=True)):
            self.assertFalse(evaluate([candidate()], state, policy(), NOW)[0].selected)
        result = evaluate([candidate()], facts(), policy(), NOW, scope="shadow")[0]
        self.assertFalse(result.selected)
        self.assertEqual(result.checks_scope, "shadow_not_preflight")

    def test_stale_account_snapshot_and_rollover(self):
        for state in (facts(observed_at="2026-10-22T14:59:00+00:00"), facts(contracts=(("MNQ", "CON.F.US.MNQ.H27"),))):
            self.assertFalse(evaluate([candidate()], state, policy(), NOW)[0].selected)

    def test_schedule_weekend_earlyclose_and_cutoff(self):
        self.assertFalse(session_facts(pd.Timestamp("2026-10-24T15:00Z"))["allow_entry"])
        self.assertFalse(session_facts(pd.Timestamp("2026-10-22T19:51Z"))["allow_entry"])
        self.assertTrue(session_facts(pd.Timestamp("2026-11-27T18:01Z"))["flatten"])

    def test_manager_has_no_submission_or_arming_path(self):
        source = inspect.getsource(strategy_manager)
        for dangerous in ("projectx_client", "practice_executor", "leader_execution", "requests.", "/api/Order/place"):
            self.assertNotIn(dangerous, source)

    def test_state_lock_cannot_be_overridden_by_policy(self):
        result = evaluate([candidate()], facts(loss_locked=True), policy(max_trade_risk=10000, max_open_risk=10000), NOW)
        self.assertIn("loss", result[0].reasons[0])
