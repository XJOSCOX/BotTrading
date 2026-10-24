"""Optional persisted forward simulation using subsequent actual micro trades."""
from contextlib import closing
import copy
import hashlib
import json
import math

import pandas as pd

from goxtrade.data.live_store import connect
from goxtrade.data.strategy_history import load_strategy_minutes
from goxtrade.execution.contracts import contract_for_symbol
from goxtrade.market.instruments import instrument
from goxtrade.market.market_session import market_session
from goxtrade.market.trading_schedule import execution_schedule
from goxtrade.research.backtest import SimulationConfig, closed_trade, manage_after_close
from goxtrade.strategies.strategy_catalog import strategy_spec
from goxtrade.strategies.vwap_ema_config import VwapEmaConfig


MICROS = {"NQ=F": "MNQ=F", "ES=F": "MES=F", "YM=F": "MYM=F"}


def advance_paper(state, candidate, ticks, minutes, symbol, contract_id, config, now):
    state = copy.deepcopy(state)
    trades = []
    active, pending = state.get("active"), state.get("pending")
    source_symbol = next((source for source, micro in MICROS.items() if micro == symbol), symbol)
    allow_entries = config.paper_enabled and config.monitor_enabled and (source_symbol in config.enabled_symbols or symbol in config.enabled_symbols)
    if not allow_entries:
        pending = None
    if active and active.get("contract_id") != contract_id:
        state["message"] = "Paper contract changed; old position retained for review, no new entries"
        return state, trades
    for tick in ticks:
        if tick["id"] <= state.get("cursor", 0):
            continue
        state["cursor"] = tick["id"]
        stamp = pd.to_datetime(tick.get("event_time"), utc=True, errors="coerce")
        if pd.isna(stamp) or tick.get("price") is None:
            continue
        price = float(tick["price"])
        if not math.isfinite(price) or price <= 0:
            continue
        if state.get("last_trade_time") and stamp < pd.Timestamp(state["last_trade_time"]):
            continue
        state["last_trade_time"] = stamp.isoformat()
        if active:
            frozen = VwapEmaConfig.from_dict(active["config_snapshot"])
            sim = SimulationConfig(quantity=active["quantity"], commission_per_side=frozen.paper_commission_per_side,
                                   slippage_ticks=frozen.paper_slippage_ticks)
            long = active["signal"] == "LONG"
            stopped = price <= active["stop"] if long else price >= active["stop"]
            targeted = price >= active["target"] if long else price <= active["target"]
            reason = "Paper scheduled flatten" if execution_schedule(stamp.to_pydatetime())["flatten"] else "Paper stop" if stopped else "Paper target" if targeted and active["exit_mode"] not in ("structure-v1", "trailing") else None
            if not reason:
                known = minutes.loc[minutes["time"]+pd.Timedelta(minutes=1) <= stamp]
                reason = manage_after_close(active, dict(close=price), known, stamp)
            if reason:
                trade = closed_trade(active, price, stamp, reason, symbol, strategy_spec("vwap_ema_cross"), sim)
                trade.update(test_type="forward_paper", provenance="Actual micro trade observations / simulated fills",
                             detection_sequence=active["detection_sequence"], entry_sequence=active["entry_sequence"],
                             exit_sequence=tick["id"])
                trades.append(trade)
                state["next_entry"] = (stamp+pd.Timedelta(minutes=frozen.cooldown_minutes)).isoformat()
                active = None
        if pending and active is None and tick["id"] > pending["paper_after_sequence"]:
            eligible = stamp >= pd.Timestamp(pending["detected_at"])
            eligible &= 0 <= (pd.Timestamp(now)-stamp).total_seconds() <= config.max_data_age_seconds
            if tick.get("received_at"):
                received = pd.to_datetime(tick["received_at"], utc=True, errors="coerce")
                eligible &= pd.notna(received) and 0 <= (pd.Timestamp(now)-received).total_seconds() <= config.max_data_age_seconds
            eligible &= (stamp-pd.Timestamp(pending["detected_at"])).total_seconds() < pending["entry_window_seconds"]
            eligible &= execution_schedule(stamp.to_pydatetime())["allow_entry"]
            if eligible:
                frozen = VwapEmaConfig.from_dict(pending["config_snapshot"])
                direction = pending.get("direction", pending["signal"])
                sign = 1 if direction == "LONG" else -1
                fill = price+sign*frozen.paper_slippage_ticks*instrument(symbol).tick_size
                active = {**pending, "signal": direction, "entry": fill, "initial_stop": pending["stop"],
                          "entry_time": stamp.isoformat(), "management_started_at": stamp.isoformat(),
                          "session": market_session(stamp.to_pydatetime())["name"], "contract_id": contract_id,
                          "quantity": frozen.paper_quantity, "entry_sequence": tick["id"]}
                breached = price <= active["stop"] if sign == 1 else price >= active["stop"]
                reached = price >= active["target"] if sign == 1 else price <= active["target"]
                if breached or (reached and active["exit_mode"] not in ("structure-v1", "trailing")):
                    sim = SimulationConfig(quantity=active["quantity"], commission_per_side=frozen.paper_commission_per_side,
                                           slippage_ticks=frozen.paper_slippage_ticks)
                    trade = closed_trade(active, price, stamp, "Paper immediate protection after fill", symbol, strategy_spec("vwap_ema_cross"), sim)
                    trade.update(test_type="forward_paper", provenance="Actual micro trades / simulated fills",
                                 detection_sequence=active["detection_sequence"], entry_sequence=tick["id"], exit_sequence=tick["id"])
                    trades.append(trade)
                    state["next_entry"] = (stamp+pd.Timedelta(minutes=frozen.cooldown_minutes)).isoformat()
                    active = None
            state["message"] = "Paper entry filled on a subsequent micro trade" if active else "Paper entry expired or no eligible fresh micro trade"
            pending = None
    event = candidate.get("unique_setup_id")
    seen = state.setdefault("seen_events", [])
    if state.get("seen_event") and state["seen_event"] not in seen:
        seen.append(state["seen_event"])
    if event and event not in seen:
        seen.append(event)
        cooldown = not state.get("next_entry") or pd.Timestamp(now) >= pd.Timestamp(state["next_entry"])
        if active is None and pending is None and allow_entries and cooldown:
            pending = {**candidate, "paper_after_sequence": state.get("cursor", 0)}
            state["message"] = "Waiting for a subsequent actual micro trade; no broker order"
    state.update(active=active, pending=pending)
    return state, trades


def forward_once(symbol, candidate, config, now):
    micro = MICROS[symbol]
    contract = contract_for_symbol(micro)
    identity = "vwap_ema_cross|" + micro
    with closing(connect()) as conn:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='strategy_paper_states'").fetchone()
        if not exists and not config.paper_enabled:
            return None
        conn.execute("CREATE TABLE IF NOT EXISTS strategy_paper_states (identity TEXT PRIMARY KEY,record TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS strategy_paper_trades (id TEXT PRIMARY KEY,record TEXT NOT NULL)")
        row = conn.execute("SELECT record FROM strategy_paper_states WHERE identity=?", (identity,)).fetchone()
        old = json.loads(row[0]) if row else {}
        if not old:
            latest = conn.execute("SELECT COALESCE(MAX(id),0) FROM live_ticks WHERE symbol=? AND contract_id=? AND event_type='trade'", (micro, contract)).fetchone()[0]
            old = dict(cursor=latest)
        rows = [dict(row) for row in conn.execute("SELECT id,price,event_time,received_at FROM live_ticks WHERE symbol=? AND contract_id=? AND event_type='trade' AND id>? ORDER BY id LIMIT 20000", (micro, contract, old.get("cursor", 0)))]
    minutes = load_strategy_minutes(micro, contract, now) if rows or old.get("active") else pd.DataFrame(columns=["time"])
    updated, trades = advance_paper(old, candidate, rows, minutes, micro, contract, config, now)
    with closing(connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute("SELECT record FROM strategy_paper_states WHERE identity=?", (identity,)).fetchone()
        if current and json.loads(current[0]) != old:
            return dict(message="Paper state advanced concurrently")
        if updated != old or not current:
            conn.execute("INSERT OR REPLACE INTO strategy_paper_states VALUES (?,?)", (identity, json.dumps(updated, default=str)))
        for trade in trades:
            key = hashlib.sha256(f"{identity}|{trade['unique_setup_id']}|{trade['entry_sequence']}|{trade['exit_sequence']}".encode()).hexdigest()
            conn.execute("INSERT OR IGNORE INTO strategy_paper_trades VALUES (?,?)", (key, json.dumps(trade)))
        conn.commit()
    return dict(message=updated.get("message", "Paper entries disabled"), active=bool(updated.get("active")), pending=bool(updated.get("pending")))


def paper_trades():
    with closing(connect()) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='strategy_paper_trades'").fetchone():
            return []
        return [json.loads(row[0]) for row in conn.execute("SELECT record FROM strategy_paper_trades")]
