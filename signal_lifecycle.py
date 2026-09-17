import json
import math

from live_store import connect
from contextlib import closing
from datetime import datetime, timezone
from adaptive_exit import MODE, update_exit
from stop_policy import aggregate_minutes
from price_ticks import price_predicate
import bot_audit


def advance_signal(state, candidate, setup_id, ticks, allow_new=True, management_bars=None):
    """Consume ordered tick IDs, keeping levels fixed until the first exit."""
    state = dict(state)
    active = state.get("active")
    if active:
        active = dict(active)
        state["active"] = active
    if active:
        management_bars = aggregate_minutes(management_bars or [],active.get("management_minutes",1))
        for tick in ticks:
            if tick["id"] <= state.get("cursor", 0) or tick["price"] is None:
                continue
            state["cursor"] = tick["id"]
            price = float(tick["price"])
            long = active["signal"] == "LONG"
            adaptive = active.get("exit_mode") == MODE
            stopped = price <= active["stop"] if long else price >= active["stop"]
            targeted = price >= active["target"] if long else price <= active["target"]
            structure_exit = None
            if adaptive and not stopped:
                structure_exit = update_exit(active, management_bars or [], dict(tick))
                stopped = price <= active["stop"] if long else price >= active["stop"]
                if targeted:
                    active["target_reached"] = True
            if stopped or structure_exit or (targeted and not adaptive):
                state["exit"] = ("Trailing stop reached" if adaptive and active["stop"] != active["initial_stop"] else "Stop reached") if stopped else (structure_exit or "Target reached")
                state["closed_management"] = dict(active)
                state['exit_price'] = price
                state['exit_time'] = dict(tick).get('event_time') or dict(tick).get('received_at')
                state["active"] = None
                active = None
                break
        # A setup seen during an active signal cannot be entered retroactively.
        state["seen"] = setup_id
    elif allow_new and setup_id and setup_id != state.get("seen") and candidate["signal"] in ("LONG", "SHORT"):
        state["seen"] = setup_id
        entry, stop, target = (candidate.get(key) for key in ("entry", "stop", "target"))
        valid = all(value is not None and math.isfinite(value) for value in (entry, stop, target))
        valid = valid and (stop < entry < target if candidate["signal"] == "LONG" else target < entry < stop)
        if valid and ticks:
            active = dict(candidate)
            if active.get("exit_mode") == MODE:
                active.update(initial_stop=active["stop"], management_started_at=datetime.now(timezone.utc).isoformat(),
                              management_status="Holding / original stop", trail_armed=False, structure_breaks=0)
            state.update(active=active, cursor=ticks[-1]["id"], exit=None, event_id=None)
        else:
            state["exit"] = "Setup already beyond its exit levels"

    if active:
        return state, {**active, "last_close": candidate.get("last_close")}
    if not allow_new:
        return state, {**candidate, "signal": "WAIT", "reason": "Waiting for fresh data during trading hours.",
                       "entry": None, "stop": None, "target": None}
    if state.get("exit") and (setup_id == state.get("seen") or candidate["signal"] not in ("LONG", "SHORT")):
        return state, {**candidate, "signal": "WAIT", "reason": state["exit"] + ". Waiting for a new setup.",
                       "entry": None, "stop": None, "target": None}
    return state, candidate


def management_timeframe(symbol, strategy):
    with closing(connect()) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='signal_lifecycle'").fetchone():
            return 1
        row = conn.execute("SELECT state FROM signal_lifecycle WHERE symbol=? AND strategy=?",(symbol,strategy)).fetchone()
    return (json.loads(row[0]).get("active") or {}).get("management_minutes",1) if row else 1


def track_signal(symbol, strategy, candidate, setup_id, allow_new, management_bars=None):
    with closing(connect()) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS signal_lifecycle (symbol TEXT, strategy TEXT, state TEXT, PRIMARY KEY(symbol, strategy))")
        init_alert_history(conn)
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT state FROM signal_lifecycle WHERE symbol=? AND strategy=?", (symbol, strategy)).fetchone()
        state = json.loads(row["state"]) if row else {}
        if state.get("active"):
            ticks = conn.execute(f"SELECT id, price,event_time,received_at FROM live_ticks WHERE symbol=? AND id>? AND {price_predicate(symbol)} ORDER BY id", (symbol, state["cursor"])).fetchall()
        else:
            ticks = conn.execute(f"SELECT id, price FROM live_ticks WHERE symbol=? AND {price_predicate(symbol)} ORDER BY id DESC LIMIT 1", (symbol,)).fetchall()
        updated, signal = advance_signal(state, candidate, setup_id, ticks, allow_new, management_bars)
        active = updated.get('active') or state.get('active')
        if active and not updated.get('event_id'):
            record = {**active, 'symbol':symbol, 'strategy':strategy, 'status':'Active',
                      'observed_at':datetime.now(timezone.utc).isoformat(), 'entry_time':None if state.get('active') else datetime.now(timezone.utc).isoformat()}
            cur = conn.execute('INSERT INTO bot_alert_history (record) VALUES (?)', (json.dumps(record),))
            updated['event_id'] = cur.lastrowid
            bot_audit.emit(f"signal:{updated['event_id']}:entry", "Signal detected", f"{symbol} / {strategy} / {active['signal']} / {active.get('trigger_detail', active.get('reason'))}", updated['event_id'], conn=conn)
        if state.get('active') and not updated.get('active') and updated.get('event_id'):
            row = conn.execute('SELECT record FROM bot_alert_history WHERE id=?', (updated['event_id'],)).fetchone()
            record = json.loads(row['record'])
            record.update(updated.get("closed_management", {}))
            record.update(status='Closed', exit_reason=updated['exit'], exit_price=updated.get('exit_price'), exit_time=updated.get('exit_time'))
            conn.execute('UPDATE bot_alert_history SET record=? WHERE id=?', (json.dumps(record),updated['event_id']))
            bot_audit.emit(f"signal:{updated['event_id']}:exit", "Signal exit", f"{updated['exit']} / observed price {updated.get('exit_price')}", updated['event_id'], conn=conn)
        elif updated.get("active") and updated.get("event_id"):
            row = conn.execute("SELECT record FROM bot_alert_history WHERE id=?", (updated["event_id"],)).fetchone()
            if row:
                record = json.loads(row["record"])
                if record.get("stop") != updated["active"].get("stop"):
                    bot_audit.emit(f"signal:{updated['event_id']}:stop", "Signal trail changed", f"{record.get('stop')} -> {updated['active'].get('stop')} / {updated['active'].get('exit_evidence', '')} / software signal level, not a broker stop amendment", updated['event_id'], conn=conn)
                if record.get("management_status") != updated["active"].get("management_status"):
                    bot_audit.emit(f"signal:{updated['event_id']}:hold", "Hold decision", str(updated['active'].get("management_status")), updated['event_id'], conn=conn)
                record.update(updated["active"])
                conn.execute("UPDATE bot_alert_history SET record=? WHERE id=?", (json.dumps(record), updated["event_id"]))
        if updated != state:
            conn.execute("INSERT OR REPLACE INTO signal_lifecycle VALUES (?, ?, ?)", (symbol, strategy, json.dumps(updated)))
        conn.commit()
        return signal


def init_alert_history(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS bot_alert_history (id INTEGER PRIMARY KEY AUTOINCREMENT, record TEXT NOT NULL)')


def alert_history(limit=200):
    with closing(connect()) as conn:
        init_alert_history(conn)
        return [dict(id=row['id'], **json.loads(row['record'])) for row in conn.execute('SELECT id,record FROM bot_alert_history ORDER BY id DESC LIMIT ?', (limit,))]
