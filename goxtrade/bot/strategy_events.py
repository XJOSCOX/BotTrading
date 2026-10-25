"""Restart-safe observations and an immutable audit record for each indicator event."""
from contextlib import closing
import json

from goxtrade.data.live_store import connect


def initialize(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS strategy_observations (identity TEXT PRIMARY KEY, record TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS strategy_signal_events (setup_id TEXT PRIMARY KEY, strategy_id TEXT NOT NULL, symbol TEXT NOT NULL, detected_at TEXT NOT NULL, record TEXT NOT NULL)")


def observation(identity):
    with closing(connect()) as conn:
        initialize(conn)
        row = conn.execute("SELECT record FROM strategy_observations WHERE identity=?", (identity,)).fetchone()
    return json.loads(row[0]) if row else {}


def recent_events(symbol, limit=100):
    with closing(connect()) as conn:
        initialize(conn)
        return [json.loads(row[0]) for row in conn.execute(
            "SELECT record FROM strategy_signal_events WHERE strategy_id='vwap_ema_cross' AND symbol=? ORDER BY detected_at DESC LIMIT ?", (symbol, limit))]


def latest_event(symbol, contract):
    with closing(connect()) as conn:
        initialize(conn)
        for row in conn.execute("SELECT record FROM strategy_signal_events WHERE strategy_id='vwap_ema_cross' AND symbol=? ORDER BY detected_at DESC", (symbol,)):
            event = json.loads(row[0])
            if event.get("source_contract") == contract:
                return event
    return None


def persist(identity, previous, updated, candidate):
    with closing(connect()) as conn:
        initialize(conn)
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT record FROM strategy_observations WHERE identity=?", (identity,)).fetchone()
        if (json.loads(row[0]) if row else {}) != previous:
            return None  # Another monitor advanced this observation; evaluate fresh data next cycle.
        if updated != previous:
            conn.execute("INSERT OR REPLACE INTO strategy_observations VALUES (?,?)", (identity, json.dumps(updated)))
        setup_id = candidate.get("unique_setup_id")
        if setup_id:
            conn.execute("INSERT OR IGNORE INTO strategy_signal_events VALUES (?,?,?,?,?)",
                         (setup_id, candidate["strategy_id"], candidate["symbol"], candidate["detected_at"], json.dumps(candidate)))
            row = conn.execute("SELECT record FROM strategy_signal_events WHERE setup_id=?", (setup_id,)).fetchone()
            candidate = json.loads(row[0])
        conn.commit()
    return candidate
