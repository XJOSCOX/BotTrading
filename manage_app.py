"""Manual double-click control for the local GoXTrade processes."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import ensure_running
import leader_execution
import live_process
import practice_executor
from execution_target import TARGETS
from projectx_client import login, post


ROOT = Path(__file__).resolve().parent
LEADER_PID = ROOT / "data" / "leader_worker.pid"


def running() -> bool:
    try:
        web_pid = int(json.loads(ensure_running.WEB_PID.read_text(encoding="utf-8"))["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        web_pid = None
    try:
        leader_pid = int(LEADER_PID.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        leader_pid = None
    return any((live_process._pid_running(web_pid), live_process.status()["running"], live_process._pid_running(leader_pid)))


def broker_flat() -> bool:
    token = login()
    accounts = post("/api/Account/search", {"onlyActiveAccounts": False}, token=token)
    if accounts.get("success") is not True:
        raise RuntimeError("Could not verify Topstep accounts")
    for target in TARGETS.values():
        if not any(row.get("id") == target["id"] and row.get("name") == target["name"] for row in accounts.get("accounts", [])):
            raise RuntimeError("Topstep account identity could not be verified")
        for endpoint, key in (("/api/Position/searchOpen", "positions"), ("/api/Order/searchOpen", "orders")):
            response = post(endpoint, {"accountId": target["id"]}, token=token)
            if response.get("success") is not True or not isinstance(response.get(key), list):
                raise RuntimeError("Could not verify open broker exposure")
            if response[key]:
                return False
    return True


def stop() -> None:
    practice_executor.pause()
    leader_execution.command("pause")
    time.sleep(2)
    for account, jobs in (("Practice", practice_executor.snapshot()[2]), ("Leader", leader_execution.snapshot()[2])):
        if any(job["state"] not in ("Closed", "Rejected") for job in jobs):
            raise RuntimeError(f"{account} has an unresolved bot order; new entries are paused, but exit monitoring must stay on")
    if not broker_flat():
        raise RuntimeError("Topstep reports an open position or order; new entries are paused, but exit monitoring must stay on")
    live_process.stop()
    for path, label in ((LEADER_PID, "leader_worker.py"), (ensure_running.WEB_PID, "streamlit")):
        try:
            payload = path.read_text(encoding="utf-8")
            pid = int(json.loads(payload)["pid"] if path == ensure_running.WEB_PID else payload)
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if live_process._pid_running(pid):
            command = subprocess.run(["powershell", "-NoProfile", "-Command", f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"], capture_output=True, text=True, timeout=10)
            if command.returncode != 0 or label.lower() not in command.stdout.lower() or str(ROOT).lower() not in command.stdout.lower():
                raise RuntimeError(f"Could not safely identify {label} process")
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=True, capture_output=True, timeout=15)
        path.unlink(missing_ok=True)
    print("GoXTrade stopped. New entries are paused.")


def start() -> None:
    live_process.DISABLED_FILE.unlink(missing_ok=True)
    ensure_running.main()
    print("GoXTrade started: http://localhost:8502")
    print("Trading controls retain their saved pause state.")


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "toggle"
    if action == "menu":
        print("GoXTrade is running." if running() else "GoXTrade is stopped.")
        print("1. Start or repair missing processes")
        print("2. Stop (requires both broker accounts flat)")
        print("3. Exit")
        selection = input("Choose 1, 2, or 3: ").strip()
        if selection == "3":
            return 0
        action = {"1": "start", "2": "stop"}.get(selection, "invalid")
    try:
        if action == "start" or action == "toggle" and not running():
            start()
        elif action == "stop" or action == "toggle" and running():
            stop()
        else:
            raise ValueError("Use start, stop, or toggle")
    except Exception as error:
        print(f"GoXTrade was not fully stopped: {error}" if action != "start" else f"GoXTrade did not start: {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
