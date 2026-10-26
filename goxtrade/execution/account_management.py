"""Explicit read-only verification before staging a replacement execution account."""
import json
from contextlib import closing
from goxtrade.config import execution_identity as identity
from goxtrade.data.live_store import connect
from goxtrade.execution.projectx_client import post
from goxtrade.runtime import live_process
from goxtrade.paths import DATA_DIR


def assert_idle(conn, action="replacing an account"):
    for profile in ("practice", "leader"):
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (profile+"_control",)).fetchone():
            row = conn.execute(f"SELECT settings FROM {profile}_control WHERE id=1").fetchone()
            if row and json.loads(row[0]).get("enabled"):
                raise ValueError(f"Pause both execution profiles before {action}")
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (profile+"_jobs",)).fetchone():
            for row in conn.execute(f"SELECT record FROM {profile}_jobs"):
                if json.loads(row[0]).get("state") not in ("Closed", "Rejected"):
                    raise ValueError("Resolve every open, pending or uncertain bot order first")


def assert_workers_stopped(action="replacing an account"):
    if live_process.status()["running"]:
        raise ValueError(f"Stop the market/execution worker before {action}")
    pidfile = DATA_DIR / "leader_worker.pid"
    if pidfile.exists():
        try:
            pid = int(pidfile.read_text())
        except (OSError, ValueError) as error:
            raise ValueError("Leader worker status is unknown; verify it is stopped") from error
        if live_process._pid_running(pid):
            raise ValueError(f"Stop the Leader worker before {action}")


def replace_account(profile, account_id, confirmed_name):
    if profile not in ("practice", "leader") or type(account_id) is not int or account_id <= 0:
        raise ValueError("Select a valid account and execution profile")
    assert_workers_stopped()
    with closing(connect()) as conn:
        assert_idle(conn)
    response = post("/api/Account/search", {"onlyActiveAccounts": False})
    if response.get("success") is not True or not isinstance(response.get("accounts"), list):
        raise ValueError("Cannot verify account list; no configuration changed")
    account = next((a for a in response["accounts"] if a.get("id") == account_id), None)
    if (not account or account.get("canTrade") is not True or account.get("simulated") is not True
            or account.get("name") != confirmed_name.strip()):
        raise ValueError("Confirm the exact name of an enabled simulated Topstep account")
    if profile == "leader" and not account["name"].startswith("50KTC-"):
        raise ValueError("Leader replacement supports 50K Trading Combine accounts only")
    targets = identity.current_targets()
    previous = targets[profile]
    unconfigured = previous["name"].startswith("YOUR_") and previous == identity.LEGACY_TARGETS[profile]
    if previous["id"] == account_id and not unconfigured:
        raise ValueError("This is already the configured account; replacement cannot reset its loss lock")
    gate_id = next((row["gate_id"] for row in identity.LEGACY_TARGETS.values() if row["id"] == account_id), account_id)
    with closing(connect()) as conn:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='execution_account_history'").fetchone():
            saved = conn.execute("SELECT profile,gate_id FROM execution_account_history WHERE account_id=?", (account_id,)).fetchone()
            if saved:
                if saved[0] != profile:
                    raise ValueError("An execution identity cannot switch between Practice and Leader")
                gate_id = saved[1]
    target = dict(id=account_id, name=account["name"], role="Leader" if profile == "leader" else "Not assigned", gate_id=gate_id)
    targets[profile] = target
    identity.validate_targets(targets)
    for number in ({account_id} if unconfigured else {previous["id"], account_id}):
        for endpoint, key in (("/api/Position/searchOpen", "positions"), ("/api/Order/searchOpen", "orders")):
            state = post(endpoint, {"accountId": number})
            if state.get("success") is not True or not isinstance(state.get(key), list) or state[key]:
                raise ValueError("Old and new accounts must be broker-verified flat with no working orders")
    with closing(connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        assert_idle(conn)
        assert_workers_stopped()
        conn.execute("CREATE TABLE IF NOT EXISTS execution_account_history(account_id INTEGER PRIMARY KEY,profile TEXT NOT NULL,gate_id INTEGER NOT NULL)")
        for record in (previous, target):
            conn.execute("INSERT OR IGNORE INTO execution_account_history VALUES(?,?,?)", (record["id"], profile, record["gate_id"]))
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (profile+"_control",)).fetchone():
            row = conn.execute(f"SELECT settings FROM {profile}_control WHERE id=1").fetchone()
            settings = json.loads(row[0]) if row else {}
            settings.pop("start_balance", None)
            settings.update(enabled=False, emergency_close=False)
            conn.execute(f"UPDATE {profile}_control SET settings=?,status=? WHERE id=1", (json.dumps(settings), json.dumps(dict(message="Account replaced; restart and explicit authorization required"))))
        # Identity changes never delete fills, reset a loss lock or arm an account.
        identity.ACCOUNT_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = identity.ACCOUNT_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(targets, indent=2), encoding="utf-8")
        temporary.replace(identity.ACCOUNT_FILE)
        conn.commit()
    return target
