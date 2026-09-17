"""Entry-only configuration. Existing positions keep their exit management."""
import json
from contextlib import closing
from live_store import connect
from bot_audit import emit
from execution_target import PROFILE, TARGETS
from strategy_catalog import STRATEGIES

DEFAULTS = dict(symbols=["MNQ", "MES", "MYM"], strategies=["CRT", "Reversal"], cooldown_minutes=5)


def init(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS bot_controls (id INTEGER PRIMARY KEY, record TEXT NOT NULL)")


def read(profile=None):
    key = TARGETS[profile or PROFILE]["gate_id"]
    with closing(connect()) as conn:
        init(conn)
        row = conn.execute("SELECT record FROM bot_controls WHERE id=?",(key,)).fetchone()
    return {**DEFAULTS, **(json.loads(row[0]) if row else {})}


def save(symbols, strategies, cooldown_minutes, profile=None):
    key = TARGETS[profile or PROFILE]["gate_id"]
    if not set(symbols) <= {"MNQ", "MES", "MYM"} or not set(strategies) <= set(STRATEGIES):
        raise ValueError("Unsupported symbol or strategy")
    if type(cooldown_minutes) is not int or not 1 <= cooldown_minutes <= 60:
        raise ValueError("Cooldown must be 1-60 minutes")
    record = dict(symbols=list(symbols), strategies=list(strategies), cooldown_minutes=cooldown_minutes)
    with closing(connect()) as conn:
        init(conn)
        conn.execute("INSERT OR REPLACE INTO bot_controls VALUES(?,?)", (key,json.dumps(record)))
        emit("controls", "Controls updated", json.dumps(record), conn=conn)
        conn.commit()


def enabled(symbol, strategy):
    settings = read()
    micro = {"NQ=F":"MNQ", "ES=F":"MES", "YM=F":"MYM"}.get(symbol)
    return micro in settings["symbols"] and strategy in settings["strategies"]
