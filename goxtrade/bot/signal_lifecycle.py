import json
import math

from goxtrade.data.live_store import connect
from contextlib import closing
from datetime import datetime, timezone
from goxtrade.strategies.adaptive_exit import MODE, update_exit
from goxtrade.strategies.stop_policy import aggregate_minutes
from goxtrade.data.price_ticks import price_predicate
from goxtrade.bot import bot_audit


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
            if active.get("strategy_id") in ("vwap_ema_cross","previous_day_box"):
                from goxtrade.strategies.adaptive_exit import timestamp
                stamp = timestamp(dict(tick).get("event_time") or dict(tick).get("received_at"))
                entered = timestamp(active.get("management_started_at") or active.get("detected_at"))
                if (stamp is None or entered is None or stamp < entered or stamp > datetime.now(timezone.utc).timestamp()
                        or not math.isfinite(price) or price <= 0):
                    continue
            long = active["signal"] == "LONG"
            adaptive = active.get("exit_mode") == MODE
            custom_trail = active.get("exit_mode") in ("trailing", "breakeven")
            stopped = price <= active["stop"] if long else price >= active["stop"]
            targeted = price >= active["target"] if long else price <= active["target"]
            structure_exit = None
            if custom_trail and not stopped:
                sign = 1 if long else -1
                risk = abs(active["entry"]-active["initial_stop"])
                favorable = (price-active["entry"])*sign
                if active["exit_mode"] == "breakeven" and favorable >= risk*active.get("breakeven_r", 1):
                    active["stop"] = max(active["stop"], active["entry"]) if long else min(active["stop"], active["entry"])
                    active["management_status"] = "Break-even stop armed"
                if active["exit_mode"] == "trailing" and favorable >= risk*active.get("trail_start_r", 1.5):
                    from goxtrade.market.instruments import round_tick
                    level = round_tick(price-sign*active["trail_ticks"]*active["tick_size"], active["tick_size"], up=not long)
                    active["stop"] = max(active["stop"], level) if long else min(active["stop"], level)
                    active["management_status"] = "Trailing tick structure"
            if adaptive and not stopped:
                structure_exit = update_exit(active, management_bars or [], dict(tick))
                stopped = price <= active["stop"] if long else price >= active["stop"]
                if targeted:
                    active["target_reached"] = True
            if stopped or structure_exit or (targeted and not adaptive and active.get("exit_mode") != "trailing"):
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
            if active.get("exit_mode") in (MODE, "trailing", "breakeven"):
                active.update(initial_stop=active["stop"], management_started_at=datetime.now(timezone.utc).isoformat(),
                              management_status="Holding / original stop", trail_armed=False, structure_breaks=0)
            if active.get("strategy_id") in ("vwap_ema_cross","previous_day_box"):
                active["management_started_at"] = active.get("detected_at") or datetime.now(timezone.utc).isoformat()
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
        if candidate.get("unique_setup_id") or candidate.get("crossover_key"):
            conn.execute("CREATE TABLE IF NOT EXISTS strategy_event_consumption (setup_id TEXT PRIMARY KEY, alert_id INTEGER)")
            conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT state FROM signal_lifecycle WHERE symbol=? AND strategy=?", (symbol, strategy)).fetchone()
        state = json.loads(row["state"]) if row else {}
        event = candidate.get("consumption_key") or candidate.get("crossover_key") or candidate.get("unique_setup_id")
        if (allow_new and not state.get("active") and setup_id != state.get("seen") and candidate.get("crossover_key")
                and not conn.execute("SELECT 1 FROM strategy_event_consumption WHERE setup_id=?", (event,)).fetchone()):
            from goxtrade.strategies.strategy_catalog import crossover_key
            for prior in conn.execute("SELECT c.alert_id,h.record FROM strategy_event_consumption c JOIN bot_alert_history h ON h.id=c.alert_id").fetchall():
                if crossover_key(json.loads(prior[1])) == event:
                    conn.execute("INSERT OR IGNORE INTO strategy_event_consumption VALUES (?,?)", (event, prior[0]))
                    break
        if event and conn.execute("SELECT 1 FROM strategy_event_consumption WHERE setup_id=?", (event,)).fetchone():
            allow_new = False
        source = state.get("active") or candidate
        source_symbol = source.get("reference_symbol") or symbol
        box_active = source.get("strategy_id") in ("previous_day_box","vwap_ema_cross")
        contract_filter = " AND contract_id=? AND event_type='trade'" if box_active else ""
        contract_args = ((state.get("active") or candidate).get("source_contract"),) if box_active else ()
        if state.get("active"):
            ticks = conn.execute(f"SELECT id, price,event_time,received_at FROM live_ticks WHERE symbol=? AND id>? AND {price_predicate(source_symbol)}{contract_filter} ORDER BY id", (source_symbol, state["cursor"],*contract_args)).fetchall()
        else:
            ticks = conn.execute(f"SELECT id, price FROM live_ticks WHERE symbol=? AND {price_predicate(source_symbol)}{contract_filter} ORDER BY id DESC LIMIT 1", (source_symbol,*contract_args)).fetchall()
        updated, signal = advance_signal(state, candidate, setup_id, ticks, allow_new, management_bars)
        active = updated.get('active') or state.get('active')
        if active and not updated.get('event_id'):
            record = {**active, 'symbol':symbol, 'strategy':strategy, 'status':'Active',
                      'observed_at':datetime.now(timezone.utc).isoformat(), 'entry_time':None if state.get('active') else datetime.now(timezone.utc).isoformat()}
            cur = conn.execute('INSERT INTO bot_alert_history (record) VALUES (?)', (json.dumps(record),))
            updated['event_id'] = cur.lastrowid
            if event:
                conn.execute("INSERT OR IGNORE INTO strategy_event_consumption VALUES (?,?)", (event, cur.lastrowid))
            bot_audit.emit(f"signal:{updated['event_id']}:entry", "Signal detected", f"{symbol} / {strategy} / {active.get('raw_signal', active['signal'])} / {active.get('trigger_detail', active.get('reason'))}", updated['event_id'], notify=active.get('strategy_id') in ('vwap_ema_cross','previous_day_box') and active.get('config_snapshot', {}).get('notify_signals', False), conn=conn)
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
