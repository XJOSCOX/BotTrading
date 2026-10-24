import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import manage_app


class ManualControlTests(unittest.TestCase):
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
