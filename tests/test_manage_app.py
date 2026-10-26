import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from goxtrade.runtime import manage_app


class InitialSetupShutdownTests(unittest.TestCase):
    def test_no_configured_accounts_require_no_authentication(self):
        with patch.object(manage_app, "TARGETS", {"practice": {"name": "YOUR_PRACTICE"}}), \
                patch.object(manage_app, "login") as login, patch.object(manage_app, "post") as post:
            self.assertTrue(manage_app.broker_flat())
            login.assert_not_called()
            post.assert_not_called()

    def test_configured_account_still_requires_broker_verification(self):
        with patch.object(manage_app, "TARGETS", {"leader": {"name": "50KTC-test", "id": 42}}), \
                patch.object(manage_app, "login", side_effect=RuntimeError("Authentication unavailable")):
            with self.assertRaisesRegex(RuntimeError, "Authentication unavailable"):
                manage_app.broker_flat()


class ManualControlTests(unittest.TestCase):
    def test_worker_maintenance_stop_leaves_web_ui_open(self):
        with patch.object(manage_app.practice_executor, "pause"), patch.object(manage_app.leader_execution, "command"), \
                patch.object(manage_app.time, "sleep"), patch.object(manage_app.practice_executor, "snapshot", return_value=({}, {}, [])), \
                patch.object(manage_app.leader_execution, "snapshot", return_value=({}, {}, [])), \
                patch.object(manage_app, "broker_flat", return_value=True), patch.object(manage_app.live_process, "stop") as stop, \
                patch.object(manage_app, "stop_owned_process") as owned:
            manage_app.stop_workers()
            stop.assert_called_once()
            owned.assert_called_once_with(manage_app.LEADER_PID, "leader_worker.py")

    def test_unresolved_job_keeps_workers_running(self):
        with patch.object(manage_app.practice_executor, "pause"), patch.object(
            manage_app.leader_execution, "command"
        ), patch.object(manage_app.time, "sleep"), patch.object(
            manage_app.practice_executor, "snapshot", return_value=({}, {}, [{"state": "Open"}])
        ), patch.object(manage_app.leader_execution, "snapshot", return_value=({}, {}, [])), patch.object(
            manage_app, "broker_flat"
        ) as broker, patch.object(manage_app.live_process, "stop") as stop:
            with self.assertRaisesRegex(RuntimeError, "unresolved bot order"):
                manage_app.stop()
            broker.assert_not_called()
            stop.assert_not_called()

    def test_start_clears_manual_feed_stop(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(
            manage_app.live_process, "DISABLED_FILE", Path(folder) / "disabled"
        ), patch.object(manage_app.ensure_running, "main") as launch:
            manage_app.live_process.DISABLED_FILE.write_text("stopped")
            manage_app.start()
            self.assertFalse(manage_app.live_process.DISABLED_FILE.exists())
            launch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
