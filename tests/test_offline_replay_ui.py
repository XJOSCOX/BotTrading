from contextlib import closing
import json
import unittest
from unittest.mock import patch
from tests import test_strategy_manager_ui as manager_ui
from tests.test_validation_lab import metadata,minutes,START,END
from goxtrade.data import lab_store,live_store
from goxtrade.diagnostics import projectx_diagnostics as diagnostics


class OfflineReplayUiTests(unittest.TestCase):
    setUp=manager_ui.StrategyManagerUiTests.setUp
    post=manager_ui.StrategyManagerUiTests.post

    def body(self):
        dataset=lab_store.save_dataset(minutes(),metadata())
        return dict(datasets=[dataset["id"]],strategies=["crt"],start=START,end=END,execution=dict(commission_per_side=.5))

    def test_replay_api_create_step_read_export_research_only(self):
        response=self.post("/api/replay",self.body())
        self.assertEqual(response.status_code,200,response.text)
        record=response.json();identifier=record["id"]
        self.assertFalse(record["broker_execution"])
        response=self.post(f"/api/replay/{identifier}/control",dict(action="step"))
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()["next_index"],1)
        chart=self.client.get(f"/api/replay/{identifier}/chart?symbol=MNQ")
        self.assertEqual(len(chart.json()["bars"]),1)
        exported=self.client.get(f"/api/replay/{identifier}/export")
        self.assertEqual(exported.json()["state"]["profile"],"research")
        self.assertNotIn("api_key",exported.text)
        with closing(live_store.connect()) as conn:
            tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse(tables & {"practice_control","leader_control","practice_jobs","leader_jobs"})

    def test_csrf_account_identity_and_unknown_controls_blocked(self):
        self.assertEqual(self.client.post("/api/replay",json=self.body()).status_code,403)
        self.assertEqual(self.post("/api/replay",{**self.body(),"profile":"leader"}).status_code,400)
        self.assertEqual(self.post("/api/replay/100001/control",dict(action="play")).status_code,400)
        self.assertEqual(self.post("/api/replay",{}).status_code,400)
        self.assertEqual(self.post("/api/replay/ticks",{}).status_code,400)

    def test_diagnostics_passive_does_not_authenticate_and_explicit_probe_sanitized(self):
        with patch.object(diagnostics,"requests") as network:
            result=self.client.get("/api/diagnostics")
            self.assertEqual(result.status_code,200,result.text)
            network.post.assert_not_called()
        self.assertEqual(self.client.post("/api/diagnostics",json=dict(action="authenticate")).status_code,403)
        with patch.object(diagnostics,"run",return_value=dict(code="AUTH_FAILED",broker_execution=False)):
            self.assertEqual(self.post("/api/diagnostics",dict(action="authenticate")).json()["code"],"AUTH_FAILED")
        self.assertEqual(self.post("/api/diagnostics",dict(action="place_order")).status_code,400)

    def test_streamlit_offline_page_renders_without_workers_or_network(self):
        from streamlit.testing.v1 import AppTest
        with patch("goxtrade.replay.replay_session._play") as play,patch.object(diagnostics,"requests") as network:
            app=AppTest.from_string("from goxtrade.ui.bot.offline_replay_panel import render\nrender()")
            app.run(timeout=20)
            self.assertFalse(app.exception)
            self.assertEqual([t.label for t in app.tabs],["Market Replay","ProjectX Diagnostics"])
            play.assert_not_called();network.post.assert_not_called()

    def test_replay_package_has_no_broker_transport_imports(self):
        import ast
        from goxtrade.paths import ROOT
        banned=("projectx_client","practice_executor","leader_execution","broker_adapter","broker_state")
        for file in (ROOT/"goxtrade"/"replay").glob("*.py"):
            tree=ast.parse(file.read_text())
            for node in ast.walk(tree):
                if isinstance(node,(ast.Import,ast.ImportFrom)):
                    names=[getattr(node,"module","") or ""]+[a.name for a in node.names]
                    self.assertFalse(any(b in name for b in banned for name in names),(file,names))


if __name__=="__main__":unittest.main()
