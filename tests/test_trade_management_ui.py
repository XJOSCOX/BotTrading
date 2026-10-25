from contextlib import closing
import unittest

from tests import test_strategy_manager_ui as manager_ui
from goxtrade.data import live_store
from goxtrade.execution.profit_policy import ProfitPolicy


class TradeManagementUiTests(unittest.TestCase):
    setUp = manager_ui.StrategyManagerUiTests.setUp
    post = manager_ui.StrategyManagerUiTests.post

    def test_shared_policy_default_off_and_roundtrip_no_account_mutation(self):
        for profile in ("practice", "leader"):
            response = self.client.get("/api/trade-management?profile="+profile)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertFalse(response.json()["policy"]["enabled"])
            self.assertFalse(response.json()["broker_changes_enabled"])
        values = ProfitPolicy(enabled=True, mode="hybrid", partial_targets=((1., 1),), management_minutes=15).to_dict()
        response = self.post("/api/trade-management/policy", values)
        self.assertEqual(response.status_code, 200, response.text)
        for profile in ("practice", "leader"):
            result = self.client.get("/api/trade-management?profile="+profile).json()
            self.assertEqual(result["policy"]["management_minutes"], 15)
            self.assertEqual(result["policy"]["partial_targets"], [[1., 1]])
            self.assertEqual(result["paper_positions"], [])
        with closing(live_store.connect()) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse(tables & {"practice_control", "leader_control", "practice_loss_gate"})

    def test_invalid_policy_csrf_and_profile_fail_closed(self):
        for invalid in (dict(extra=True), dict(mode="partial"), dict(partial_targets=[[1., .5]]),
                        dict(retain_fraction=1), dict(management_minutes=1), dict(enabled="yes")):
            self.assertEqual(self.post("/api/trade-management/policy", invalid).status_code, 400)
        self.assertEqual(self.client.post("/api/trade-management/policy", json={}).status_code, 403)
        self.assertEqual(self.client.get("/api/trade-management?profile=funded").status_code, 422)

    def test_comparison_requires_data_and_costs(self):
        self.assertEqual(self.post("/api/trade-management/compare", dict(datasets=[])).status_code, 422)
        from tests.test_portfolio_backtest import minutes
        payload = dict(datasets=[dict(symbol="MNQ", contract_id="CON.F.US.MNQ.Z26", csv=minutes().to_csv(index=False))], walk_forward=False, compare=False)
        self.assertEqual(self.post("/api/trade-management/compare", payload).status_code, 400)
        from goxtrade.execution.execution_policy import ExecutionPolicy
        self.assertEqual(self.post("/api/manager/policy", ExecutionPolicy(commission_per_side=.5, participating=()).to_dict()).status_code, 200)
        response = self.post("/api/trade-management/compare", payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["result"]["policies"]), 10)
        self.assertEqual(response.json()["result"]["broker_checks"], "NOT_PERFORMED")

    def test_streamlit_both_profiles_render_without_broker_calls(self):
        from streamlit.testing.v1 import AppTest
        for profile in ("practice", "leader"):
            app = AppTest.from_string("from goxtrade.ui.bot.trade_management_panel import render\nrender("+repr(profile)+")")
            app.run(timeout=20)
            self.assertFalse(app.exception)
            self.assertEqual([tab.label for tab in app.tabs], ["Positions", "Exit policy", "Giveback review", "Policy comparison"])

