import tempfile
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from goxtrade.runtime import live_process


class LiveProcessTests(unittest.TestCase):
    def test_build_identity_tracks_source_not_runtime_data(self):
        from goxtrade.runtime.build_identity import fingerprint
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            source=root/'worker.py';source.write_text('original')
            first=fingerprint(root)
            (root/'runtime.json').write_text('new runtime state')
            self.assertEqual(fingerprint(root),first)
            source.write_text('updated')
            self.assertNotEqual(fingerprint(root),first)

    def test_windows_probe_requires_exact_pid_and_verified_response(self):
        with patch.object(live_process.os,'name','nt'),patch.object(live_process.subprocess,'run') as run:
            run.return_value=Mock(returncode=0,stderr='',stdout='"python.exe","1234","Console","1","2,000 K"\n')
            self.assertFalse(live_process._pid_running(123))
            self.assertTrue(live_process._pid_running(1234))
            run.return_value=Mock(returncode=0,stderr='',stdout='INFO: No tasks are running which match the specified criteria.')
            self.assertFalse(live_process._pid_running(123))
            for result in (Mock(returncode=1,stderr='denied',stdout=''),Mock(returncode=0,stderr='',stdout=''),Mock(returncode=0,stderr='',stdout='unrecognized output')):
                run.return_value=result
                with self.assertRaises(live_process.ProcessInspectionError):live_process._pid_running(123)
            run.side_effect=subprocess.TimeoutExpired('tasklist',5)
            with self.assertRaises(live_process.ProcessInspectionError):live_process._pid_running(123)

    def test_unknown_or_dead_status_never_deletes_registration(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(live_process,'PID_FILE',Path(folder)/'worker.pid'):
            original=json.dumps(dict(pid=123,started_at='fixture'))
            live_process.PID_FILE.write_text(original)
            for outcome in (False,live_process.ProcessInspectionError('restricted')):
                with patch.object(live_process,'_pid_running',**({'return_value':outcome} if outcome is False else {'side_effect':outcome})):
                    result=live_process.status()
                    self.assertEqual(result['running'],False if outcome is False else None)
                    self.assertEqual(result['pid'],123)
                    self.assertEqual(live_process.PID_FILE.read_text(),original)
            live_process.PID_FILE.write_text('{bad')
            self.assertIsNone(live_process.status()['running'])
            self.assertEqual(live_process.PID_FILE.read_text(),'{bad')

    def test_unknown_state_blocks_launch_and_kill(self):
        with patch.object(live_process,'status',return_value=dict(running=None,error='Unknown')),patch.object(live_process.subprocess,'Popen') as launch,patch.object(live_process.subprocess,'run') as kill:
            with self.assertRaises(live_process.ProcessInspectionError):live_process._start()
            with self.assertRaises(live_process.ProcessInspectionError):live_process._stop()
            launch.assert_not_called();kill.assert_not_called()

    def test_failed_or_unconfirmed_stop_retains_registration(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(live_process,'DATA_DIR',Path(folder)),patch.object(live_process,'PID_FILE',Path(folder)/'worker.pid'),patch.object(live_process,'DISABLED_FILE',Path(folder)/'disabled'),patch.object(live_process,'status',return_value=dict(running=True,pid=123)),patch.object(live_process.os,'name','nt'),patch.object(live_process,'_creationflags',return_value=0),patch.object(live_process.time,'sleep'),patch.object(live_process,'_pid_running',return_value=True),patch.object(live_process.subprocess,'run') as run:
            live_process.PID_FILE.write_text('{"pid":123}')
            verified=Mock(returncode=0,stdout=str(live_process.ROOT)+' run_live_market.py')
            run.side_effect=[verified,subprocess.CalledProcessError(1,'taskkill')]
            with self.assertRaises(subprocess.CalledProcessError):live_process._stop()
            self.assertTrue(live_process.PID_FILE.exists())
            run.side_effect=[verified,Mock(returncode=0)]
            with self.assertRaises(live_process.ProcessInspectionError):live_process._stop()
            self.assertTrue(live_process.PID_FILE.exists())
            run.side_effect=[Mock(returncode=0,stdout='unrelated.exe')]
            with self.assertRaises(live_process.ProcessInspectionError):live_process._stop()
            self.assertEqual(run.call_count,5)

    def test_lifecycle_lock_rejects_concurrent_owner(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(live_process,'DATA_DIR',Path(folder)):
            with live_process.control_lock():
                with self.assertRaises(OSError):
                    with live_process.control_lock():self.fail('Concurrent lifecycle lock accepted')

    def test_intentional_stop_blocks_automatic_restart_until_manual_start(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live_process, "DATA_DIR", Path(folder)), patch.object(
            live_process, "LOG_DIR", Path(folder)
        ), patch.object(live_process, "PID_FILE", Path(folder) / "live_market.pid"), patch.object(
            live_process, "DISABLED_FILE", Path(folder) / "live_market.disabled"
        ), patch.object(live_process, "OUT_LOG", Path(folder) / "out.log"), patch.object(
            live_process, "ERR_LOG", Path(folder) / "err.log"
        ), patch.object(live_process, "status", return_value={"running": False, "pid": None}), patch.object(
            live_process.subprocess, "Popen", return_value=Mock(pid=123)
        ) as launch:
            live_process.stop()
            self.assertTrue(live_process.DISABLED_FILE.exists())
            live_process.start()
            self.assertFalse(live_process.DISABLED_FILE.exists())
            command = launch.call_args.args[0]
            self.assertEqual(Path(command[1]), live_process.ROOT / "goxtrade" / "runtime" / "run_live_market.py")
            self.assertTrue(Path(command[1]).is_file())
            self.assertIn(str(live_process.ROOT), launch.call_args.kwargs["env"]["PYTHONPATH"])


if __name__ == "__main__":
    unittest.main()
