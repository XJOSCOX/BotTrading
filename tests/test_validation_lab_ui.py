from contextlib import closing
import hashlib
import json
import unittest
from unittest.mock import patch

from tests import test_strategy_manager_ui as manager_ui
from tests.test_validation_lab import metadata,minutes,START,END
from goxtrade.research import lab_service,validation_lab as lab
from goxtrade.data import lab_store as store,live_store
from goxtrade.strategies.strategy_catalog import SPECS


class ValidationLabUiTests(unittest.TestCase):
    setUp=manager_ui.StrategyManagerUiTests.setUp
    post=manager_ui.StrategyManagerUiTests.post

    def payload(self):
        meta=metadata()
        meta.pop("granularity")
        return {**meta,"csv":minutes().to_csv(index=False)}

    def test_import_read_export_and_quality_are_research_only(self):
        response=self.post("/api/validation-lab/import",self.payload())
        self.assertEqual(response.status_code,200,response.text)
        saved=response.json()["dataset"]
        self.assertTrue(saved["quality"]["eligible"])
        overview=self.client.get("/api/validation-lab").json()
        self.assertEqual(len(overview["strategies"]),7)
        self.assertFalse(overview["broker_execution"])
        csv=self.client.get("/api/validation-lab/datasets/"+saved["id"]+"/export")
        self.assertEqual(csv.status_code,200)
        self.assertIn("volume_provenance",csv.text)
        with closing(live_store.connect()) as conn:
            tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse(tables & {"practice_control","leader_control","practice_loss_gate"})

    def test_bad_requests_csrf_and_unsupported_modes_fail_without_launch(self):
        with patch("goxtrade.research.lab_jobs.start") as launch:
            self.assertEqual(self.post("/api/validation-lab/history",{}).status_code,400)
            self.assertEqual(self.post("/api/validation-lab/run",{}).status_code,400)
            self.assertEqual(self.client.post("/api/validation-lab/history",json={}).status_code,403)
            invalid=self.payload();invalid["csv"]=minutes().iloc[:-1].to_csv(index=False)
            result=self.post("/api/validation-lab/import",invalid).json()["dataset"]
            self.assertEqual(self.post("/api/validation-lab/run",dict(datasets=[result["id"]],strategies=["crt"],start=START,end=END,execution=dict(commission_per_side=.5))).status_code,400)
            launch.assert_not_called()

    def test_job_run_report_and_trade_export(self):
        saved=lab_service.import_csv(self.payload())
        body=dict(datasets=[saved["id"]],strategies=["crt"],start=START,end=END,execution=dict(commission_per_side=.5))
        with patch("goxtrade.research.lab_jobs.start",side_effect=lambda identifier:store.get("lab_jobs",identifier)):
            response=self.post("/api/validation-lab/run",body)
        self.assertEqual(response.status_code,200,response.text)
        identifier=response.json()["job"]["id"]
        lab.execute(identifier)
        for format in ("html","csv"):
            response=self.client.get(f"/api/validation-lab/runs/{identifier}/export?format={format}")
            self.assertEqual(response.status_code,200,response.text)
            self.assertNotIn("Bearer",response.text)
        self.assertEqual(self.client.get(f"/api/validation-lab/runs/{identifier}").status_code,200)
        self.assertEqual(self.client.get(f"/api/validation-lab/runs/{identifier}/trades/0").status_code,400)

    def test_same_catalog_and_independent_new_strategy_opt_ins(self):
        self.assertTrue(all(spec.execution_profiles==("practice","leader") for spec in SPECS))
        with patch("goxtrade.execution.leader_execution.command") as leader,patch("goxtrade.execution.practice_executor.arm") as practice:
            for endpoint in ("vwap","previous-day-box"):
                response=self.post("/api/"+endpoint,dict(leader_enabled=True,practice_enabled=False))
                self.assertEqual(response.status_code,200,response.text)
                result=self.client.get("/api/config").json()["vwap" if endpoint=="vwap" else "previous_day_box"]
                self.assertTrue(result["leader_enabled"])
                self.assertFalse(result["practice_enabled"])
            leader.assert_not_called();practice.assert_not_called()

    def test_legacy_fingerprints_survive_new_permission_field(self):
        from goxtrade.strategies.vwap_ema_config import VwapEmaConfig
        from goxtrade.strategies.previous_day_box_config import PreviousDayBoxConfig
        for config in (VwapEmaConfig(),PreviousDayBoxConfig()):
            values=config.to_dict();values.pop("leader_enabled")
            original=hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()[:16]
            self.assertEqual(config.fingerprint,original)

    def test_streamlit_validation_lab_renders_without_starting_workers(self):
        from streamlit.testing.v1 import AppTest
        with patch("goxtrade.research.lab_jobs.start") as launch:
            app=AppTest.from_string("from goxtrade.ui.bot.validation_lab_panel import render\nrender()")
            app.run(timeout=20)
            self.assertFalse(app.exception)
            self.assertEqual([tab.label for tab in app.tabs],["Datasets","Backtesting","Results","Jobs"])
            launch.assert_not_called()

    def test_slow_attribution_snapshot_does_not_delay_price_stream(self):
        import time
        def slow():
            time.sleep(2)
            return dict(profiles={},monitor=[],alerts=[],events=[])
        with patch.object(self.client.app.state,"sockets",0),patch("goxtrade.api.state.CACHE.get",side_effect=slow),patch("goxtrade.api.state.ticks",return_value=dict(prices={},time="fixture")):
            began=time.monotonic()
            with self.client.websocket_connect(self.base.replace("http://","ws://")+"/api/stream",headers={"origin":self.base}) as socket:
                ticks=[]
                while len(ticks)<3:
                    item=socket.receive_json()
                    if item["type"]=="ticks":ticks.append(item)
                self.assertLess(time.monotonic()-began,1.5)
