"""Leader UI adapter. Execution code runs only in a separate, fixed-target process."""
from contextlib import closing
from pathlib import Path
import json
import os
import subprocess
import sys
from live_store import connect
from execution_target import TARGETS

TARGET = TARGETS["leader"]
ROOT = Path(__file__).resolve().parent


def environment():
    return {**os.environ,"GOX_EXECUTION_PROFILE":"leader"}


def snapshot():
    with closing(connect()) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='leader_control'").fetchone():
            return dict(enabled=False,quantities=dict(MNQ=3,MES=3,MYM=3),enable_mym=False),{},[]
        row = conn.execute("SELECT settings,status FROM leader_control WHERE id=1").fetchone()
        if not row:
            return {},{},[]
        jobs = [json.loads(r[0]) for r in conn.execute("SELECT record FROM leader_jobs ORDER BY alert_id DESC")]
    return json.loads(row[0]),json.loads(row[1]),jobs


def history():
    with closing(connect()) as conn:
        if conn.execute("SELECT count(*) FROM sqlite_master WHERE name IN ('leader_fills','leader_history_status')").fetchone()[0] != 2:
            return {},[]
        row = conn.execute("SELECT record FROM leader_history_status WHERE id=1").fetchone()
        fills = [json.loads(r[0]) for r in conn.execute("SELECT record FROM leader_fills")]
    return json.loads(row[0]) if row else {},sorted(fills,key=lambda r:r["creationTimestamp"],reverse=True)


def command(action, **values):
    result = subprocess.run([sys.executable,str(ROOT/"leader_worker.py"),"command"],input=json.dumps(dict(action=action,**values)),
                            cwd=ROOT,env=environment(),capture_output=True,text=True,timeout=40,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
    try:
        response = json.loads(result.stdout)
    except (ValueError,TypeError):
        raise RuntimeError("Leader command outcome unavailable. Inspect status before retrying.")
    if not response.get("success"):
        raise ValueError(response.get("message","Leader command failed"))


def start_worker():
    from live_process import _pid_running
    pidfile = ROOT/"data"/"leader_worker.pid"
    if pidfile.exists():
        try:
            if _pid_running(int(pidfile.read_text())):
                return
        except (ValueError,OSError):
            pass
    logs = ROOT/"data"/"logs"
    logs.mkdir(parents=True,exist_ok=True)
    # Restarting a stopped worker restores exit management, never automatic entries.
    command("pause")
    with (logs/"leader_worker.log").open("a") as log:
        process = subprocess.Popen([sys.executable,str(ROOT/"leader_worker.py")],cwd=ROOT,env=environment(),
                                   stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
    pidfile.write_text(str(process.pid))
