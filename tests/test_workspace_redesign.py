from contextlib import closing
from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from goxtrade.config import execution_identity as identity
from goxtrade.data import live_store
from goxtrade.execution import account_management as accounts, projectx_client


class AccountReplacementTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.base = dict(practice=dict(id=101, name="PRAC-OLD", role="Not assigned", gate_id=1),
                         leader=dict(id=202, name="50KTC-OLD", role="Leader", gate_id=202))
        for patcher in (patch.object(live_store, "DB_PATH", Path(self.folder.name)/"test.db"),
                        patch.object(identity, "ACCOUNT_FILE", Path(self.folder.name)/"accounts.json"),
                        patch.object(identity, "LEGACY_TARGETS", self.base), patch.object(identity, "TARGETS", self.base),
                        patch.object(accounts, "assert_workers_stopped")):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.new = dict(id=303, name="50KTC-NEW", canTrade=True, simulated=True)
        self.requests = []

    def response(self, endpoint, payload):
        self.requests.append((endpoint, payload))
        if endpoint == "/api/Account/search":
            return dict(success=True, accounts=[self.new])
        self.assertIn(endpoint, ("/api/Position/searchOpen", "/api/Order/searchOpen"))
        return dict(success=True, positions=[], orders=[])

    def replace(self):
        with patch.object(accounts, "post", side_effect=self.response):
            return accounts.replace_account("leader", 303, "50KTC-NEW")

    def test_replacement_verified_read_only_restart_required_history_preserved(self):
        with closing(live_store.connect()) as conn:
            conn.execute("CREATE TABLE leader_control(id INTEGER PRIMARY KEY,settings TEXT,status TEXT)")
            conn.execute("INSERT INTO leader_control VALUES (1,?, '{}')", (json.dumps(dict(enabled=False, start_balance=50000, quantities=dict(MNQ=3))),))
            conn.execute("CREATE TABLE leader_jobs(alert_id INTEGER,record TEXT)")
            conn.execute("INSERT INTO leader_jobs VALUES(7,?)", (json.dumps(dict(state="Closed", account_id=202)),))
            conn.execute("CREATE TABLE practice_loss_gate(id INTEGER PRIMARY KEY,record TEXT)")
            conn.execute("INSERT INTO practice_loss_gate VALUES(202,?)", (json.dumps(dict(locked=True, loss=500)),))
            conn.commit()
        result = self.replace()
        self.assertEqual(result["id"], 303)
        self.assertEqual(identity.TARGETS["leader"]["id"], 202)
        self.assertTrue(identity.restart_required())
        with self.assertRaises(ValueError):
            identity.assert_current("leader")
        with closing(live_store.connect()) as conn:
            settings = json.loads(conn.execute("SELECT settings FROM leader_control").fetchone()[0])
            self.assertFalse(settings["enabled"])
            self.assertNotIn("start_balance", settings)
            self.assertEqual(settings["quantities"]["MNQ"], 3)
            self.assertEqual(conn.execute("SELECT count(*) FROM leader_jobs").fetchone()[0], 1)
            self.assertTrue(json.loads(conn.execute("SELECT record FROM practice_loss_gate WHERE id=202").fetchone()[0])["locked"])
        self.assertEqual(len(self.requests), 5)

    def test_enabled_or_unresolved_profile_blocks_before_api(self):
        with closing(live_store.connect()) as conn:
            conn.execute("CREATE TABLE practice_control(id INTEGER PRIMARY KEY,settings TEXT)")
            conn.execute("INSERT INTO practice_control VALUES(1,?)", (json.dumps(dict(enabled=True)),))
            conn.commit()
        with patch.object(accounts, "post") as api, self.assertRaises(ValueError):
            accounts.replace_account("leader", 303, "50KTC-NEW")
        api.assert_not_called()
        self.assertFalse(identity.ACCOUNT_FILE.exists())

    def test_uncertain_jobs_cannot_be_erased_by_replacement(self):
        with closing(live_store.connect()) as conn:
            conn.execute("CREATE TABLE leader_jobs(record TEXT)")
            conn.execute("INSERT INTO leader_jobs VALUES(?)", (json.dumps(dict(state="Unknown")),))
            conn.commit()
        with self.assertRaises(ValueError):
            self.replace()

    def test_unavailable_funded_and_wrong_name_rejected(self):
        for changes in (dict(canTrade=False), dict(simulated=False), dict(name="WRONG")):
            with self.subTest(changes=changes), patch.dict(self.new, changes), self.assertRaises(ValueError):
                self.replace()
        self.assertFalse(identity.ACCOUNT_FILE.exists())

    def test_open_or_unverifiable_broker_exposure_blocks(self):
        for state in (dict(success=False), dict(success=True, positions=[dict(size=1)])):
            def response(endpoint, payload):
                return self.response(endpoint, payload) if endpoint == "/api/Account/search" else state
            with self.subTest(state=state), patch.object(accounts, "post", side_effect=response), self.assertRaises(ValueError):
                accounts.replace_account("leader", 303, "50KTC-NEW")
        self.assertFalse(identity.ACCOUNT_FILE.exists())

    def test_same_account_does_not_reset_gate(self):
        self.new.update(id=202, name="50KTC-OLD")
        with patch.object(accounts, "post", side_effect=self.response), self.assertRaises(ValueError):
            accounts.replace_account("leader", 202, "50KTC-OLD")

    def test_corrupt_override_fails_closed(self):
        identity.ACCOUNT_FILE.write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            identity.assert_current("practice")

    def test_reselecting_previous_account_retains_original_gate(self):
        self.replace()
        self.new.update(id=202, name="50KTC-OLD")
        with patch.object(accounts, "post", side_effect=self.response):
            result = accounts.replace_account("leader", 202, "50KTC-OLD")
        self.assertEqual(result["gate_id"], 202)

    def test_initial_placeholder_is_not_queried_as_a_broker_account(self):
        self.base["leader"]["name"] = "YOUR_LEADER_ACCOUNT"
        self.replace()
        numbers = [payload["accountId"] for endpoint, payload in self.requests if endpoint != "/api/Account/search"]
        self.assertEqual(numbers, [303, 303])


class WorkspaceUiTests(unittest.TestCase):
    def test_first_run_without_local_python_account_file_stays_unconfigured(self):
        import builtins
        import runpy
        original = builtins.__import__
        def without_local(name, *args, **kwargs):
            if name == "goxtrade.config.execution_target":
                raise ModuleNotFoundError("Missing local configuration", name=name)
            return original(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=without_local):
            values = runpy.run_path(identity.__file__)
        self.assertTrue(values["TARGETS"]["practice"]["name"].startswith("YOUR_"))
        self.assertTrue(values["TARGETS"]["leader"]["name"].startswith("YOUR_"))

    def test_all_pages_render_without_api_calls_or_arming(self):
        from streamlit.testing.v1 import AppTest
        from goxtrade.ui.shell import PAGES
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store, "DB_PATH", Path(folder)/"ui.db"), \
                patch.object(projectx_client, "post", side_effect=AssertionError("No API calls during offline rendering")) as broker, \
                patch.object(projectx_client, "credentials_present", return_value=False):
            for page, _, _ in PAGES:
                with self.subTest(page=page):
                    app = AppTest.from_file("app.py")
                    app.query_params["page"] = page
                    app.run(timeout=30)
                    self.assertFalse(app.exception, [error.message for error in app.exception])
            broker.assert_not_called()

    def test_controls_save_cooldown_and_quantities_without_arming(self):
        from streamlit.testing.v1 import AppTest
        from goxtrade.execution import practice_executor
        from goxtrade.bot import bot_controls
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store, "DB_PATH", Path(folder)/"controls.db"), \
                patch.object(projectx_client, "post", side_effect=AssertionError("No broker orders")) as broker:
            app = AppTest.from_string("from goxtrade.ui.control_center import render\nrender()")
            app.run(timeout=30)
            app.number_input(key="controls_cooldown_practice").set_value(9)
            app.number_input(key="controls_qty_practiceMNQ").set_value(3)
            next(button for button in app.button if button.label == "Save execution policy").click().run(timeout=30)
            self.assertFalse(app.exception, [error.message for error in app.exception])
            self.assertEqual(bot_controls.read("practice")["cooldown_minutes"], 9)
            self.assertEqual(practice_executor.snapshot()[0]["quantities"]["MNQ"], 3)
            self.assertFalse(practice_executor.snapshot()[0].get("enabled"))
            broker.assert_not_called()

    def test_navigation_retains_old_page_links(self):
        from goxtrade.ui.shell import ALIASES
        self.assertEqual(ALIASES, dict(Market="Charts", Bot="Strategies", Live="Execution"))

    def test_credentials_preserve_unrelated_settings_and_do_not_leak(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(projectx_client, "ENV_PATH", Path(folder)/".env"), patch.dict(os.environ):
            projectx_client.ENV_PATH.write_text("UNRELATED='keep me'\n", encoding="utf-8")
            projectx_client.save_credentials("test-user", "test's secret")
            self.assertIn("UNRELATED='keep me'", projectx_client.ENV_PATH.read_text())
            self.assertEqual(os.environ["TOPSTEP_API_KEY"], "test's secret")
            for username, key in (("", "secret"), ("user\nBAD=1", "secret")):
                with self.assertRaises(ValueError):
                    projectx_client.save_credentials(username, key)
