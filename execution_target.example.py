"""Fixed execution identities. A worker selects its target only at process startup."""
import os

TARGETS = {
    "practice": dict(id=100001, name="YOUR_PRACTICE_ACCOUNT", role="Not assigned", gate_id=1),
    "leader": dict(id=100002, name="YOUR_LEADER_ACCOUNT", role="Leader", gate_id=100002),
}
PROFILE = os.environ.get("GOX_EXECUTION_PROFILE", "practice")
if PROFILE not in TARGETS:
    raise RuntimeError("Unknown execution target; refusing to start")
TARGET = TARGETS[PROFILE]


def assert_other_idle(conn):
    """Call within the same write transaction that enables or claims execution."""
    other = "leader" if PROFILE == "practice" else "practice"
    import json
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (other+"_control",)).fetchone():
        row = conn.execute(f"SELECT settings FROM {other}_control WHERE id=1").fetchone()
        if row and json.loads(row[0]).get("enabled"):
            raise ValueError(f"Pause {other} execution before switching accounts")
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (other+"_jobs",)).fetchone():
        if any(json.loads(r[0])["state"] not in ("Closed", "Rejected") for r in conn.execute(f"SELECT record FROM {other}_jobs")):
            raise ValueError(f"Resolve all {other} bot orders before switching accounts")
