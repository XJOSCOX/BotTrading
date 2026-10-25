from contextlib import closing
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from goxtrade.api import app as api_module, state
from goxtrade.data import live_store
from goxtrade.execution import projectx_client, manager_service
from goxtrade.execution.execution_policy import ExecutionPolicy
from goxtrade.strategies.strategy_catalog import SPECS


class StrategyManagerUiTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        for patcher in (patch.object(live_store, "DB_PATH", Path(folder.name)/"manager.db"),
                        patch.object(state, "CACHE", state.SnapshotCache()),
                        patch.object(projectx_client, "post", side_effect=AssertionError("No broker calls")),
                        patch.object(projectx_client, "login", side_effect=AssertionError("No login"))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.base = f"http://127.0.0.1:{api_module.PORT}"
        self.client = TestClient(api_module.create_app(), base_url=self.base, raise_server_exceptions=False)
        self.addCleanup(self.client.close)
        response = self.client.get("/api/session")
        self.headers = {"origin": self.base, "x-gox-csrf": response.json()["csrf"]}

    def post(self, path, body):
        return self.client.post(path, json=body, headers=self.headers)

    def test_both_profiles_same_manager_catalog_and_policy(self):
        results = []
        for profile in ("practice", "leader"):
            response = self.client.get("/api/manager?profile="+profile)
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertFalse(result["broker_cutover_enabled"])
            self.assertFalse(result["policy"]["paper_enabled"])
            self.assertEqual(set(result["policy"]["monitoring"]), {spec.id for spec in SPECS})
            results.append(result["policy"])
        self.assertEqual(results[0], results[1])

    def test_shared_research_settings_never_modify_broker_tables(self):
        values = ExecutionPolicy(commission_per_side=.5).to_dict()
        values.update(symbols=["MNQ", "MES", "MYM"], cooldown_minutes=12, max_trade_risk=60.)
        response = self.post("/api/manager/policy", values)
        self.assertEqual(response.status_code, 200, response.text)
        for profile in ("practice", "leader"):
            result = self.client.get("/api/manager?profile="+profile).json()
            self.assertEqual(result["policy"]["cooldown_minutes"], 12)
            self.assertEqual(result["policy"]["symbols"], ["MNQ", "MES", "MYM"])
        with closing(live_store.connect()) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertNotIn("practice_control", tables)
            self.assertNotIn("leader_control", tables)
            self.assertNotIn("practice_loss_gate", tables)

    def test_invalid_settings_and_csrf_fail_closed(self):
        for values in (dict(unknown=True), dict(max_daily_loss=501), dict(paper_enabled=True), dict(commission_per_side=0)):
            self.assertEqual(self.post("/api/manager/policy", values).status_code, 400)
        self.assertEqual(self.client.post("/api/manager/policy", json={}).status_code, 403)
        self.assertEqual(self.post("/api/manager/paper/start", {}).status_code, 400)
        self.assertFalse(manager_service.policy().paper_enabled)

    def test_shadow_paper_and_unknown_profile_never_submit(self):
        for profile in ("practice", "leader"):
            response = self.post("/api/manager/evaluate/"+profile, {})
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.post("/api/manager/paper", {}).status_code, 200)
        self.assertEqual(self.client.get("/api/manager?profile=funded").status_code, 422)

    def test_research_requires_actual_data_and_valid_costs(self):
        self.assertEqual(self.post("/api/manager/backtest", dict(datasets=[])).status_code, 422)
        from tests.test_portfolio_backtest import minutes
        source = minutes()
        values = dict(datasets=[dict(symbol="MNQ", contract_id="CON.F.US.MNQ.Z26", csv=source.to_csv(index=False))], compare=False, walk_forward=False)
        self.assertEqual(self.post("/api/manager/backtest", values).status_code, 400)
        self.assertEqual(self.post("/api/manager/policy", ExecutionPolicy(commission_per_side=.5, participating=()).to_dict()).status_code, 200)
        response = self.post("/api/manager/backtest", values)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["result"]["broker_checks"], "NOT_PERFORMED")

    def test_settings_and_local_data_defaults_remain_separate(self):
        with closing(live_store.connect()) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM live_ticks").fetchone()[0], 0)
        result = self.post("/api/manager/paper", {}).json()
        self.assertFalse(result["result"]["enabled"])
