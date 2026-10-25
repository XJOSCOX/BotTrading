"""Declared collector connection windows, not a claim of exchange exactly-once delivery."""
from contextlib import closing
import pandas as pd
from goxtrade.data.live_store import connect


def initialize(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS strategy_feed_windows (id INTEGER PRIMARY KEY,symbol TEXT,contract_id TEXT,opened_at TEXT NOT NULL,closed_at TEXT)")


def opened(symbol, contract_id, now):
    stamp = pd.Timestamp(now).tz_convert("UTC").isoformat()
    with closing(connect()) as conn:
        initialize(conn)
        close_windows(conn, symbol, contract_id, stamp)
        conn.execute("INSERT INTO strategy_feed_windows(symbol,contract_id,opened_at) VALUES (?,?,?)", (symbol, contract_id, stamp))
        conn.commit()


def closed(symbol, contract_id, now):
    with closing(connect()) as conn:
        initialize(conn)
        close_windows(conn, symbol, contract_id, pd.Timestamp(now).tz_convert("UTC").isoformat())
        conn.commit()


def close_windows(conn, symbol, contract_id, stamp):
    latest = conn.execute("SELECT MAX(received_at) FROM live_ticks WHERE symbol=? AND contract_id=?", (symbol, contract_id)).fetchone()[0]
    for row in conn.execute("SELECT id,opened_at FROM strategy_feed_windows WHERE symbol=? AND contract_id=? AND closed_at IS NULL", (symbol, contract_id)).fetchall():
        end = max(pd.Timestamp(row[1]), min(pd.Timestamp(stamp), pd.Timestamp(latest or row[1])))
        conn.execute("UPDATE strategy_feed_windows SET closed_at=? WHERE id=?", (end.isoformat(), row[0]))


def windows(conn, symbol, contract_id):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='strategy_feed_windows'").fetchone():
        return []
    return [(pd.Timestamp(row[0]), pd.Timestamp(row[1]) if row[1] else None)
            for row in conn.execute("SELECT opened_at,closed_at FROM strategy_feed_windows WHERE symbol=? AND contract_id=?", (symbol, contract_id))]
