"""Explicit worker lifecycle commands; the interface and entry authorization stay separate."""
from contextlib import closing

from goxtrade.config import execution_identity
from goxtrade.data.live_store import connect
from goxtrade.execution import account_management, leader_execution, projectx_client
from goxtrade.runtime import live_process, manage_app


def status():
    feed = live_process.status()
    try:
        pid = int(manage_app.LEADER_PID.read_text())
        leader = dict(running=live_process._pid_running(pid), pid=pid)
    except FileNotFoundError:
        leader = dict(running=False, pid=None)
    except (OSError, ValueError):
        leader = dict(running=None, pid=None)
    return dict(market=feed, leader=leader)


def command(action):
    if action not in ("start", "restart", "stop"):
        raise ValueError("Unsupported service action")
    if action in ("stop", "restart"):
        manage_app.stop_workers()
    if action in ("start", "restart"):
        execution_identity.assert_current("practice")
        execution_identity.assert_current("leader")
        if not projectx_client.credentials_present():
            raise ValueError("Save API credentials before starting services")
        with closing(connect()) as conn:
            account_management.assert_idle(conn, action="starting all workers")
        live_process.start()
        leader_execution.start_worker()
    return dict(message=("All trading workers stopped. Interface remains open." if action == "stop"
                         else "Workers started. Trading remains paused; authorize entries separately in Execution."),
                services=status())
