"""Entry-only configuration. Existing positions keep their exit management."""
import json
from contextlib import closing
from goxtrade.data.live_store import connect
from goxtrade.bot.bot_audit import emit
from goxtrade.config.execution_identity import PROFILE, TARGETS
from goxtrade.strategies.strategy_catalog import STRATEGIES, strategy_spec, execution_block

DEFAULTS = dict(symbols=["MNQ", "MES", "MYM"], strategies=["CRT", "Reversal"], cooldown_minutes=5,
                entry_confirmation_mode="strict")


def init(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS bot_controls (id INTEGER PRIMARY KEY, record TEXT NOT NULL)")


def read(profile=None):
    key = TARGETS[profile or PROFILE]["gate_id"]
    with closing(connect()) as conn:
        init(conn)
        row = conn.execute("SELECT record FROM bot_controls WHERE id=?",(key,)).fetchone()
    return {**DEFAULTS, **(json.loads(row[0]) if row else {})}


def save(symbols, strategies, cooldown_minutes, profile=None, *, entry_confirmation_mode=None):
    selected_profile = profile or PROFILE
    key = TARGETS[profile or PROFILE]["gate_id"]
    if not set(symbols) <= {"MNQ", "MES", "MYM"} or not set(strategies) <= set(STRATEGIES):
        raise ValueError("Unsupported symbol or strategy")
    if type(cooldown_minutes) is not int or not 1 <= cooldown_minutes <= 60:
        raise ValueError("Cooldown must be 1-60 minutes")
    if any(selected_profile not in strategy_spec(strategy).execution_profiles for strategy in strategies):
        raise ValueError("A selected strategy is not eligible for this execution profile")
    mode = entry_confirmation_mode if entry_confirmation_mode is not None else read(selected_profile)["entry_confirmation_mode"]
    if mode not in ("strict", "standard") or selected_profile == "leader" and mode != "strict":
        raise ValueError("Standard confirmation is available for Practice only")
    record = dict(symbols=list(symbols), strategies=list(strategies), cooldown_minutes=cooldown_minutes,
                  entry_confirmation_mode=mode)
    with closing(connect()) as conn:
        init(conn)
        conn.execute("INSERT OR REPLACE INTO bot_controls VALUES(?,?)", (key,json.dumps(record)))
        emit("controls", "Controls updated", json.dumps(record), conn=conn)
        conn.commit()


def enabled(symbol, strategy):
    settings = read()
    micro = {"NQ=F":"MNQ", "ES=F":"MES", "YM=F":"MYM"}.get(symbol)
    if micro not in settings["symbols"] or strategy not in settings["strategies"]:
        return False
    try:
        return execution_block(dict(strategy=strategy, entry_mode="CONFIRMED"), PROFILE) is None
    except (ValueError, KeyError, TypeError):
        return False
