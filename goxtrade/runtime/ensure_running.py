"""Start missing GoXTrade processes from the manual launcher."""
from __future__ import annotations

import json
import msvcrt
import subprocess
import sys
from contextlib import closing
from datetime import datetime, timezone

from goxtrade.execution import leader_execution
from goxtrade.runtime import live_process
from goxtrade.paths import ROOT


DATA = ROOT / "data"
LOGS = DATA / "logs"
WEB_PID = DATA / "streamlit.pid"
LOCK = DATA / "ensure_running.lock"


def log(message: str) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    with (LOGS / "launcher.log").open("a", encoding="utf-8") as output:
        output.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")


def start_web() -> None:
    try:
        pid = int(json.loads(WEB_PID.read_text(encoding="utf-8"))["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        pid = None
    if live_process._pid_running(pid):
        return
    LOGS.mkdir(parents=True, exist_ok=True)
    with closing((LOGS / "streamlit.out.log").open("a", encoding="utf-8")) as output, closing(
        (LOGS / "streamlit.err.log").open("a", encoding="utf-8")
    ) as error:
        process = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"),
             "--server.port", "8502", "--server.headless", "true"],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=error,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    WEB_PID.write_text(json.dumps({"pid": process.pid}), encoding="utf-8")
    log(f"Web server started (PID {process.pid})")


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    with LOCK.open("a+b") as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return
        try:
            start_web()
            if not live_process.DISABLED_FILE.exists() and not live_process.status()["running"]:
                started = live_process.start()
                log(f"Feed/monitor started (PID {started['pid']})")
            leader_execution.start_worker()
        except Exception as error:
            log(f"Launcher failed: {type(error).__name__}: {error}")
            raise
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


if __name__ == "__main__":
    main()
