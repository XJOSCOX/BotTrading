"""Persistent realized account-loss gate, separate from resettable run limits."""
import json
import math
from contextlib import closing
from datetime import datetime, timezone
from live_store import connect


def check(balance, fallback=None, acknowledge=False, account_id=1):
    balance = float(balance)
    if not math.isfinite(balance):
        raise ValueError("Account balance unavailable")
    with closing(connect()) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS practice_loss_gate (id INTEGER PRIMARY KEY, record TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS practice_loss_approvals (time TEXT, previous TEXT, balance REAL)")
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT record FROM practice_loss_gate WHERE id=?",(account_id,)).fetchone()
        state = json.loads(row[0]) if row else dict(baseline=float(fallback if fallback is not None else balance), locked=False)
        state["balance"] = balance
        state["account_id"] = account_id
        state["loss"] = max(0, state["baseline"] - balance)
        state["locked"] = state["locked"] or state["loss"] >= 500
        if acknowledge and state["locked"]:
            conn.execute("INSERT INTO practice_loss_approvals VALUES (?,?,?)", (datetime.now(timezone.utc).isoformat(), json.dumps(state), balance))
            state.update(baseline=balance, loss=0, locked=False)
        conn.execute("INSERT OR REPLACE INTO practice_loss_gate VALUES (?,?)", (account_id,json.dumps(state)))
        conn.commit()
    return state


def snapshot(account_id=1):
    with closing(connect()) as conn:
        exists = conn.execute("SELECT name FROM sqlite_master WHERE name='practice_loss_gate'").fetchone()
        row = conn.execute("SELECT record FROM practice_loss_gate WHERE id=?",(account_id,)).fetchone() if exists else None
    return json.loads(row[0]) if row else {}
