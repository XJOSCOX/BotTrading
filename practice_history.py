"""Read-only Practice fill history, persisted independently of page navigation."""
import json
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from threading import Event, Thread

import streamlit as st

from live_store import connect
from practice_executor import ACCOUNT_ID, ACCOUNT_NAME
from projectx_client import login, post
from execution_target import PROFILE


def db():
    conn = connect()
    conn.execute(f"CREATE TABLE IF NOT EXISTS {PROFILE}_fills (id INTEGER PRIMARY KEY, record TEXT NOT NULL)")
    conn.execute(f"CREATE TABLE IF NOT EXISTS {PROFILE}_history_status (id INTEGER PRIMARY KEY, record TEXT NOT NULL)")
    conn.commit()
    return conn


def write_status(**values):
    with closing(db()) as conn:
        conn.execute(f"INSERT OR REPLACE INTO {PROFILE}_history_status VALUES (1,?)", (json.dumps(values),))
        conn.commit()


def snapshot():
    with closing(db()) as conn:
        state = conn.execute(f"SELECT record FROM {PROFILE}_history_status WHERE id=1").fetchone()
        fills = [json.loads(r[0]) for r in conn.execute(f"SELECT record FROM {PROFILE}_fills")]
    fills.sort(key=lambda r: (datetime.fromisoformat(r["creationTimestamp"]).timestamp(), r["id"]), reverse=True)
    return json.loads(state[0]) if state else {}, fills


def refresh(token):
    accounts = post("/api/Account/search", {"onlyActiveAccounts": False}, token=token)
    account = next((a for a in accounts.get("accounts", []) if a.get("id") == ACCOUNT_ID), {})
    if accounts.get("success") is not True or account.get("name") != ACCOUNT_NAME or account.get("simulated") is not True:
        raise ValueError("Practice identity not verified")
    now = datetime.now(timezone.utc)
    response = post("/api/Trade/search", {"accountId": ACCOUNT_ID,
                    "startTimestamp": (now - timedelta(days=7)).isoformat(),
                    "endTimestamp": now.isoformat()}, token=token)
    if response.get("success") is not True:
        raise ValueError("Practice history unavailable")
    positions = post("/api/Position/searchOpen", {"accountId": ACCOUNT_ID}, token=token)
    orders = post("/api/Order/searchOpen", {"accountId": ACCOUNT_ID}, token=token)
    if positions.get("success") is not True or orders.get("success") is not True:
        raise ValueError("Practice open state unavailable")
    fills = response["trades"]
    # Validate the entire response before committing any rows.
    for row in fills:
        if row.get("accountId") != ACCOUNT_ID:
            raise ValueError("Unexpected history account")
        int(row["id"])
        datetime.fromisoformat(row["creationTimestamp"])
    with closing(db()) as conn:
        conn.executemany(f"INSERT OR REPLACE INTO {PROFILE}_fills VALUES (?,?)",
                         [(r["id"], json.dumps(r)) for r in fills])
        conn.commit()
    write_status(updated_at=now.isoformat(), error=False,
                 positions=positions["positions"], orders=orders["orders"])


def totals(fills):
    valid = [r for r in fills if not r.get("voided")]
    closed = [r for r in valid if r.get("profitAndLoss") is not None]
    return dict(wins=sum(r["profitAndLoss"] > 0 for r in closed),
                losses=sum(r["profitAndLoss"] < 0 for r in closed),
                pnl=sum(r["profitAndLoss"] for r in closed),
                fees=sum(r.get("fees") or 0 for r in valid))


def run():
    token, authenticated = None, 0
    while True:
        try:
            if token is None or time.monotonic() - authenticated > 3600:
                token, authenticated = login(), time.monotonic()
            refresh(token)
        except Exception:
            previous, _ = snapshot()
            write_status(**{**previous, "error": True})
            token = None
        Event().wait(15)


@st.cache_resource
def ensure_worker():
    worker = Thread(target=run, name="practice-history-readonly", daemon=True)
    worker.start()
    return worker
