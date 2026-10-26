from contextlib import ExitStack
import unittest
from unittest.mock import patch

from goxtrade.runtime import service_control as services


class ServiceControlTests(unittest.TestCase):
    def mocks(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        return {name: stack.enter_context(patch.object(owner, name, **kwargs)) for owner, name, kwargs in (
            (services, "status", {"return_value": {}}),
            (services.manage_app, "stop_workers", {}),
            (services.execution_identity, "assert_current", {}),
            (services.projectx_client, "credentials_present", {"return_value": True}),
            (services, "connect", {}),
            (services.account_management, "assert_idle", {}),
            (services.live_process, "start", {}),
            (services.leader_execution, "start_worker", {}),
        )}

    def test_start_launches_both_workers_without_arming(self):
        calls = self.mocks()
        result = services.command("start")
        calls["assert_idle"].assert_called_once()
        calls["start"].assert_called_once()
        calls["start_worker"].assert_called_once()
        calls["stop_workers"].assert_not_called()
        self.assertIn("Trading remains paused", result["message"])

    def test_stop_never_restarts(self):
        calls = self.mocks()
        services.command("stop")
        calls["stop_workers"].assert_called_once()
        calls["start"].assert_not_called()
        calls["start_worker"].assert_not_called()

    def test_restart_checks_shutdown_before_starting(self):
        calls = self.mocks()
        order = []
        calls["stop_workers"].side_effect = lambda: order.append("stop")
        calls["start"].side_effect = lambda: order.append("feed")
        calls["start_worker"].side_effect = lambda: order.append("leader")
        services.command("restart")
        self.assertEqual(order, ["stop", "feed", "leader"])

    def test_open_position_blocks_restart_and_keeps_monitoring(self):
        calls = self.mocks()
        calls["stop_workers"].side_effect = RuntimeError("Open broker position")
        with self.assertRaisesRegex(RuntimeError, "Open broker position"):
            services.command("restart")
        calls["start"].assert_not_called()
        calls["start_worker"].assert_not_called()

    def test_enabled_profile_blocks_start(self):
        calls = self.mocks()
        calls["assert_idle"].side_effect = ValueError("Pause both profiles")
        with self.assertRaises(ValueError):
            services.command("start")
        calls["start"].assert_not_called()
        calls["start_worker"].assert_not_called()

    def test_missing_credentials_blocks_start(self):
        calls = self.mocks()
        calls["credentials_present"].return_value = False
        with self.assertRaisesRegex(ValueError, "Save API credentials"):
            services.command("start")
        calls["start"].assert_not_called()

    def test_invalid_action_has_no_side_effects(self):
        calls = self.mocks()
        with self.assertRaises(ValueError):
            services.command("invalid")
        calls["start"].assert_not_called()
        calls["stop_workers"].assert_not_called()
