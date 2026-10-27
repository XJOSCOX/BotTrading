from __future__ import annotations

import json
import csv
import io
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from goxtrade.paths import ROOT
from goxtrade.runtime.environment import worker_environment


DATA_DIR = ROOT / "data"
LOG_DIR = DATA_DIR / "logs"
PID_FILE = DATA_DIR / "live_market.pid"
DISABLED_FILE = DATA_DIR / "live_market.disabled"
OUT_LOG = LOG_DIR / "live_market.out.log"
ERR_LOG = LOG_DIR / "live_market.err.log"


class ProcessInspectionError(RuntimeError):
    """Unknown process state must never authorize a second worker or a kill."""


@contextmanager
def control_lock(name='market_control.lock'):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with (DATA_DIR / name).open('a+b') as lock:
        lock.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == 'nt':
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def _creationflags():
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _pid_running(pid: int | None) -> bool:
    if not pid:
        return False
    if type(pid) is not int or pid <= 0:
        raise ProcessInspectionError('Invalid process registration; inspect workers before retrying')
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, creationflags=_creationflags(), timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ProcessInspectionError('Windows process inspection unavailable') from error
        if result.returncode != 0 or result.stderr.strip():
            raise ProcessInspectionError('Windows process inspection failed; worker state is unknown')
        rows=list(csv.reader(io.StringIO(result.stdout)))
        listed=[int(row[1]) for row in rows if len(row)>=2 and row[1].isdigit()]
        if listed:
            return pid in listed
        if result.stdout.strip().startswith('INFO: No tasks are running'):
            return False
        raise ProcessInspectionError('Windows process response could not be verified')
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError as error:
        raise ProcessInspectionError('Process inspection unavailable') from error


def _read_pid() -> dict | None:
    if not PID_FILE.exists():
        return None
    try:
        payload=json.loads(PID_FILE.read_text(encoding="utf-8"))
        if not isinstance(payload,dict) or type(payload.get('pid')) is not int or payload['pid']<=0:
            raise ValueError('Invalid registration')
        return payload
    except (OSError, ValueError) as error:
        raise ProcessInspectionError('Worker registration unreadable; inspect processes before starting') from error


def status() -> dict:
    payload = None
    error = None
    try:
        payload = _read_pid()
        running = _pid_running(payload['pid'] if payload else None)
    except ProcessInspectionError as problem:
        running, error = None, str(problem)
    pid = payload.get('pid') if payload else None
    return {
        "running": running,
        "pid": pid,
        "started_at": payload.get("started_at") if payload else None,
        "error": error,
        "stdout_log": str(OUT_LOG),
        "stderr_log": str(ERR_LOG),
    }


def start() -> dict:
    with control_lock():
        return _start()


def _start() -> dict:
    current = status()
    if current['running'] is None:
        raise ProcessInspectionError(current.get('error') or 'Worker state unknown; not starting another worker')
    if current["running"]:
        return {**current, "message": "Live feed is already running."}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stdout = OUT_LOG.open("a", encoding="utf-8")
    stderr = ERR_LOG.open("a", encoding="utf-8")
    try:
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "goxtrade" / "runtime" / "run_live_market.py")],
            cwd=str(ROOT),
            env=worker_environment(),
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
    DISABLED_FILE.unlink(missing_ok=True)
    return {**status(), "message": "Live feed started."}


def stop() -> dict:
    with control_lock():
        return _stop()


def _stop() -> dict:
    current = status()
    if current['running'] is None:
        raise ProcessInspectionError(current.get('error') or 'Worker state unknown; nothing terminated')
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DISABLED_FILE.write_text("Stopped by user\n", encoding="utf-8")
    pid = current.get("pid")
    if not current["running"] or not pid:
        return {**current, "message": "Live feed is not running."}
    if os.name == "nt":
        info=subprocess.run(['powershell','-NoProfile','-Command',f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"],
                            capture_output=True,text=True,timeout=10,creationflags=_creationflags())
        if info.returncode or str(ROOT).lower() not in info.stdout.lower() or 'run_live_market.py' not in info.stdout.lower():
            raise ProcessInspectionError('Recorded PID is not a verified market worker; nothing terminated')
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=True, timeout=15, creationflags=_creationflags())
    else:
        os.kill(pid, 15)
    for _ in range(30):
        if not _pid_running(pid):
            break
        time.sleep(.1)
    else:
        raise ProcessInspectionError('Worker exit not confirmed; process registration retained')
    PID_FILE.unlink(missing_ok=True)
    return {**status(), "message": "Live feed stopped."}


def tail(path: str, lines: int = 30) -> str:
    file_path = Path(path)
    if not file_path.exists():
        return ""
    return "\n".join(file_path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])

