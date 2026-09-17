from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
LOG_DIR = DATA_DIR / "logs"
PID_FILE = DATA_DIR / "live_market.pid"
OUT_LOG = LOG_DIR / "live_market.out.log"
ERR_LOG = LOG_DIR / "live_market.err.log"


def _creationflags():
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _pid_running(pid: int | None) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            creationflags=_creationflags(),
            timeout=5,
        )
        return result.returncode == 0 and str(pid) in result.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_pid() -> dict | None:
    if not PID_FILE.exists():
        return None
    try:
        return json.loads(PID_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def status() -> dict:
    payload = _read_pid()
    pid = payload.get("pid") if payload else None
    running = _pid_running(pid)
    if payload and not running:
        PID_FILE.unlink(missing_ok=True)
    return {
        "running": running,
        "pid": pid if running else None,
        "started_at": payload.get("started_at") if payload and running else None,
        "stdout_log": str(OUT_LOG),
        "stderr_log": str(ERR_LOG),
    }


def start() -> dict:
    current = status()
    if current["running"]:
        return {**current, "message": "Live feed is already running."}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stdout = OUT_LOG.open("a", encoding="utf-8")
    stderr = ERR_LOG.open("a", encoding="utf-8")
    try:
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "run_live_market.py")],
            cwd=str(ROOT),
            stdout=stdout,
            stderr=stderr,
            stdin=subprocess.DEVNULL,
            creationflags=_creationflags(),
        )
    finally:
        stdout.close()
        stderr.close()
    payload = {"pid": process.pid, "started_at": datetime.now().isoformat(timespec="seconds")}
    PID_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {**status(), "message": "Live feed started."}


def stop() -> dict:
    current = status()
    pid = current.get("pid")
    if not current["running"] or not pid:
        return {**current, "message": "Live feed is not running."}
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=_creationflags())
    else:
        os.kill(pid, 15)
    PID_FILE.unlink(missing_ok=True)
    return {**status(), "message": "Live feed stopped."}


def tail(path: str, lines: int = 30) -> str:
    file_path = Path(path)
    if not file_path.exists():
        return ""
    return "\n".join(file_path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])

