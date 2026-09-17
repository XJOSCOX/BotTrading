"""Offline candle simulation. Never imports an executor or submits orders."""
from contextlib import closing
import json
from datetime import datetime, timezone
import pandas as pd
from live_store import connect
from crt_strategy import evaluate_crt
from reversal_strategy import evaluate_reversal
from stop_policy import buffered_signal
from adaptive_exit import update_exit
from market_session import market_session

PROFILES = {"CRT": dict(structure_lookback=5, break_confirmations=2, trail_start_r=2.0),
            "Reversal": dict(structure_lookback=3, break_confirmations=1, trail_start_r=1.0)}
POINTS = {"NQ=F": 2.0, "ES=F": 5.0, "YM=F": .5}


def load_bars(symbol, hours=48):
    """Read already-saved bars only; never fetch or rebuild live data."""
    frames = []
    with closing(connect()) as conn:
        for table in ("chart_minutes", "historical_minutes"):
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
                frames.append(pd.read_sql_query(f"SELECT time,open,high,low,close FROM {table} WHERE symbol=? ORDER BY time", conn, params=(symbol,)))
    if not frames:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close"])
    frame = pd.concat(frames).drop_duplicates("time", keep="last")
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    now = pd.Timestamp.now(tz="UTC").floor("min")
    return frame[(frame.time >= now-pd.Timedelta(hours=hours)) & (frame.time < now)].sort_values("time").reset_index(drop=True)


def filter_reason(bars, session, sessions, max_range_atr=0):
    if not session["is_open"] or session["name"] not in sessions:
        return "Session filter"
    if max_range_atr:
        window = bars.tail(15)
        if len(window) < 15 or not window.time.diff().iloc[1:].eq(pd.Timedelta(minutes=1)).all():
            return "Volatility warmup / gap"
        prev = window.close.shift(1)
        atr = pd.concat([window.high-window.low, (window.high-prev).abs(), (window.low-prev).abs()], axis=1).max(axis=1).iloc[:-1].mean()
        if atr <= 0 or (window.iloc[-1].high-window.iloc[-1].low) > max_range_atr*atr:
            return "Oversized signal candle"
    return None


def simulate(bars, symbol, strategy, candidate=False, sessions=None, max_range_atr=0, quantity=1, fees=0., slippage_ticks=0., cooldown=5):
    if symbol not in POINTS or strategy not in PROFILES or type(quantity) is not int or not 1 <= quantity <= 4:
        raise ValueError("Unsupported replay configuration")
    if min(fees, slippage_ticks, max_range_atr, cooldown) < 0:
        raise ValueError("Replay costs and settings must not be negative")
    bars = bars.copy().sort_values("time").reset_index(drop=True)
    bars["time"] = pd.to_datetime(bars["time"], utc=True)
    if bars.time.duplicated().any() or bars[["open", "high", "low", "close"]].isna().any().any():
        raise ValueError("Replay requires unique, valid candles")
    sessions = ["Regular", "Extended", "Overnight"] if sessions is None else sessions
    tick = 1 if symbol == "YM=F" else .25
    slip = tick*slippage_ticks
    active, seen, next_entry = None, None, None
    trades, blocks, management = [], {}, []
    for i, bar in enumerate(bars.to_dict("records")):
        now = bar["time"]
        key = now.floor("15min") if strategy == "CRT" else now
        completed = bars.iloc[:i]
        closed_at = now+pd.Timedelta(minutes=1)
        management.append({**bar, "time": now.isoformat(), "closed_at": closed_at.isoformat()})
        if active is None and key != seen and (next_entry is None or now >= next_entry):
            seen = key
            session = market_session(now.to_pydatetime())
            reason = filter_reason(completed, session, sessions, max_range_atr)
            if reason:
                blocks[reason] = blocks.get(reason, 0)+1
            elif i >= 16:
                # The in-progress candle exposes only its open, never its future high/low/close.
                current = pd.DataFrame([dict(time=now, open=bar["open"], high=bar["open"], low=bar["open"], close=bar["open"])])
                known = pd.concat([completed, current], ignore_index=True)
                if strategy == "CRT":
                    grouped = known.set_index("time").resample("15min").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"), count=("close", "count")).dropna()
                    grouped = grouped[(grouped["count"] == 15) | (grouped.index == key)]
                    signal = evaluate_crt(grouped.reset_index())
                else:
                    signal = evaluate_reversal(known)[0]
                signal["tick_size"] = tick
                signal = buffered_signal(signal, management[:-1])
                if signal["signal"] in ("LONG", "SHORT"):
                    sign = 1 if signal["signal"] == "LONG" else -1
                    entry = bar["open"]+sign*slip
                    if (entry-signal["stop"])*sign > 0 and (signal["target"]-entry)*sign > 0:
                        active = {**signal, "entry":entry, "initial_stop":signal["stop"], "management_started_at":now.isoformat(), "entry_time":now.isoformat(), "session":session["name"], "strategy":strategy, "structure_breaks":0}
                        if candidate:
                            active.update(PROFILES[strategy])
        elif active:
            seen = key
        if active:
            sign = 1 if active["signal"] == "LONG" else -1
            hit = bar["low"] <= active["stop"] if sign == 1 else bar["high"] >= active["stop"]
            reason = "Stop / conservative OHLC" if hit else None
            exit_price = (min(bar["open"],active["stop"]) if sign == 1 else max(bar["open"],active["stop"])) if hit else None
            if not hit:
                reason = update_exit(active, management, dict(event_time=closed_at.isoformat()))
                exit_price = bar["close"] if reason else None
            if reason:
                exit_price -= sign*slip
                gross = (exit_price-active["entry"])*sign*POINTS[symbol]*quantity
                trades.append(dict(strategy=strategy, symbol=symbol, session=active["session"], direction=active["signal"], entry_time=active["entry_time"], time=closed_at.isoformat(), entry=active["entry"], exit=exit_price, reason=reason, quantity=quantity, gross=gross, costs=fees*quantity, net=gross-fees*quantity))
                active = None
                next_entry = closed_at+pd.Timedelta(minutes=cooldown)
    return dict(trades=trades, blocks=blocks, open_at_end=bool(active), candles=len(bars))


def save_run(config, result):
    with closing(connect()) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS bot_replays (id INTEGER PRIMARY KEY, time TEXT, config TEXT, result TEXT)")
        cursor = conn.execute("INSERT INTO bot_replays(time,config,result) VALUES(?,?,?)", (datetime.now(timezone.utc).isoformat(), json.dumps(config), json.dumps(result)))
        conn.commit()
        return cursor.lastrowid


def saved_runs():
    with closing(connect()) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='bot_replays'").fetchone():
            return []
        return [dict(id=r[0], time=r[1], config=json.loads(r[2]), result=json.loads(r[3])) for r in conn.execute("SELECT * FROM bot_replays ORDER BY id DESC LIMIT 20")]
