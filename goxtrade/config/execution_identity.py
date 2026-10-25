"""Validated local account overrides, frozen for each worker's lifetime."""
import json
import os
from goxtrade.paths import DATA_DIR

try:
    from goxtrade.config.execution_target import TARGETS as LEGACY_TARGETS
except ModuleNotFoundError as error:
    if error.name != "goxtrade.config.execution_target":
        raise
    LEGACY_TARGETS = {
        "practice": dict(id=100001, name="YOUR_PRACTICE_ACCOUNT", role="Not assigned", gate_id=1),
        "leader": dict(id=100002, name="YOUR_LEADER_ACCOUNT", role="Leader", gate_id=100002),
    }

PROFILE = os.environ.get("GOX_EXECUTION_PROFILE", "practice")
if PROFILE not in ("practice", "leader"):
    raise ValueError("Unknown execution profile; refusing to start")

ACCOUNT_FILE = DATA_DIR / "execution_accounts.json"


def validate_targets(values):
    if not isinstance(values, dict) or set(values) != {"practice", "leader"}:
        raise ValueError("Both execution profiles must have an explicit account")
    for profile, target in values.items():
        if (not isinstance(target, dict) or type(target.get("id")) is not int or target["id"] <= 0
                or not isinstance(target.get("name"), str) or not target["name"].strip()
                or type(target.get("gate_id")) is not int or target["gate_id"] <= 0
                or target.get("role") != ("Leader" if profile == "leader" else "Not assigned")):
            raise ValueError("Invalid execution account identity")
        if profile == "practice" and not target["name"].startswith("PRAC-") and target != LEGACY_TARGETS["practice"]:
            raise ValueError("Practice requires a PRAC account, never a Combine or funded account")
    if values["practice"]["id"] == values["leader"]["id"]:
        raise ValueError("Practice and Leader must be different accounts")
    if values["practice"]["gate_id"] == values["leader"]["gate_id"]:
        raise ValueError("Practice and Leader must have separate loss locks")
    return values


def current_targets():
    if not ACCOUNT_FILE.exists():
        return {profile: dict(target) for profile, target in LEGACY_TARGETS.items()}
    try:
        return validate_targets(json.loads(ACCOUNT_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError) as error:
        raise ValueError("Account configuration is invalid; execution is blocked") from error


TARGETS = current_targets()
TARGET = TARGETS[PROFILE]


def assert_current(profile=PROFILE):
    if current_targets()[profile] != TARGETS[profile]:
        raise ValueError("Account changed. Restart the app and workers before enabling entries")


def restart_required():
    return current_targets() != TARGETS


def assert_other_idle(conn):
    other = "leader" if PROFILE == "practice" else "practice"
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (other+"_control",)).fetchone():
        row = conn.execute(f"SELECT settings FROM {other}_control WHERE id=1").fetchone()
        if row and json.loads(row[0]).get("enabled"):
            raise ValueError(f"Pause {other} execution before switching accounts")
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (other+"_jobs",)).fetchone():
        if any(json.loads(row[0]).get("state") not in ("Closed", "Rejected") for row in conn.execute(f"SELECT record FROM {other}_jobs")):
            raise ValueError(f"Resolve all {other} bot orders before switching accounts")
