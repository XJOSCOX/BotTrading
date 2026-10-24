"""Regression checks for persistent paths and relocated worker entry points."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from goxtrade.data import live_store
from goxtrade.execution import contracts, leader_execution, live_accounts, projectx_client
from goxtrade.paths import CONFIG_DIR, ROOT
from goxtrade.runtime import live_process
from goxtrade.runtime.environment import worker_environment


class ProjectLayoutTests(unittest.TestCase):
    def test_persistent_files_keep_their_existing_locations(self):
        self.assertEqual(ROOT, Path(__file__).resolve().parent.parent)
        self.assertEqual(live_store.DB_PATH, ROOT / "data" / "live_market.db")
        self.assertEqual(contracts.CONTRACTS_FILE, ROOT / "data" / "contracts.json")
        self.assertEqual(live_accounts.SETTINGS, ROOT / "data" / "live_preferences.json")
        self.assertEqual(projectx_client.ENV_PATH, ROOT / ".env")
        self.assertEqual(live_accounts.COPY_PROFILE, CONFIG_DIR / "copy_accounts.json")
        self.assertEqual(live_process.PID_FILE, ROOT / "data" / "live_market.pid")

    def test_leader_command_uses_relocated_script_and_isolated_profile(self):
        with patch.object(leader_execution.subprocess, "run", return_value=Mock(stdout='{"success": true}')) as run:
            leader_execution.command("pause")
        command = run.call_args.args[0]
        self.assertEqual(Path(command[1]), ROOT / "goxtrade" / "execution" / "leader_worker.py")
        self.assertTrue(Path(command[1]).is_file())
        self.assertEqual(command[2], "command")
        self.assertEqual(run.call_args.kwargs["cwd"], ROOT)
        environment = run.call_args.kwargs["env"]
        self.assertEqual(environment["GOX_EXECUTION_PROFILE"], "leader")
        self.assertEqual(environment["PYTHONPATH"].split(os.pathsep)[0], str(ROOT))

    def test_worker_scripts_import_from_outside_the_project_directory(self):
        script = "import runpy,sys; runpy.run_path(sys.argv[1], run_name='layout_import_check')"
        workers = (
            (ROOT / "goxtrade" / "runtime" / "run_live_market.py", "practice"),
            (ROOT / "goxtrade" / "execution" / "leader_worker.py", "leader"),
        )
        with tempfile.TemporaryDirectory() as directory:
            for path, profile in workers:
                with self.subTest(worker=path.name):
                    result = subprocess.run(
                        [sys.executable, "-c", script, str(path)], cwd=directory,
                        env=worker_environment(GOX_EXECUTION_PROFILE=profile),
                        capture_output=True, text=True, timeout=20,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
