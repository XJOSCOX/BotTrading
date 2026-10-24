import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import live_process


class LiveProcessTests(unittest.TestCase):
    def test_intentional_stop_blocks_automatic_restart_until_manual_start(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live_process, "DATA_DIR", Path(folder)), patch.object(
            live_process, "LOG_DIR", Path(folder)
        ), patch.object(live_process, "PID_FILE", Path(folder) / "live_market.pid"), patch.object(
            live_process, "DISABLED_FILE", Path(folder) / "live_market.disabled"
        ), patch.object(live_process, "OUT_LOG", Path(folder) / "out.log"), patch.object(
            live_process, "ERR_LOG", Path(folder) / "err.log"
        ), patch.object(live_process, "status", return_value={"running": False, "pid": None}), patch.object(
            live_process.subprocess, "Popen", return_value=Mock(pid=123)
        ):
            live_process.stop()
            self.assertTrue(live_process.DISABLED_FILE.exists())
            live_process.start()
            self.assertFalse(live_process.DISABLED_FILE.exists())


if __name__ == "__main__":
    unittest.main()
