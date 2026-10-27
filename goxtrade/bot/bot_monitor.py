"""Background watch-only evaluation, independent of the Streamlit page."""
import json
import logging
import time
import pandas as pd
from contextlib import closing
from datetime import datetime, timezone
from threading import Event

from goxtrade.strategies.crt_strategy import evaluate_crt, minute_candles_from_ticks
from goxtrade.strategies.reversal_strategy import evaluate_reversal
from goxtrade.data.live_store import connect, price_history_for_symbol, ticks_for_symbol
from goxtrade.market.market_session import market_session, session_signal
from goxtrade.bot.signal_lifecycle import track_signal, alert_history
from goxtrade.strategies.adaptive_exit import MODE
from goxtrade.strategies.stop_policy import buffered_signal
from goxtrade.bot import bot_audit
from goxtrade.strategies.strategy_catalog import STRATEGIES, strategy_spec
from goxtrade.strategies.continuation_strategies import evaluate_orb, evaluate_vwap, evaluate_ema_pullback, completed
from goxtrade.strategies.strategy_settings import read_orb_minutes, read_stop_minutes
from goxtrade.data.chart_history import chart_history

SYMBOLS = ("NQ=F", "ES=F", "YM=F")


def format_price(value):
    return "-" if value is None else f"{float(value):,.2f}"


def evaluate_strategy_status(symbol, strategy, session, data, allow_new=True, candles_1m=None) -> dict:
    from importlib import import_module
    spec = strategy_spec(strategy)
    if spec.runtime_adapter:
        return import_module(spec.runtime_adapter).evaluate_status(symbol, spec.name, session, allow_new)
    from goxtrade.strategies.signal_candles import signal_candles
    from goxtrade.bot.signal_lifecycle import management_timeframe
    source = chart_history(symbol) if candles_1m is None else candles_1m
    interval = spec.signal_minutes
    closed = signal_candles(source,session["time"],interval)
    price = float(data.iloc[-1]["price"]) if not data.empty else None
    tick = 1.0 if symbol == "YM=F" else .25
    # Legacy evaluators reserve the final row for live price, not confirmation.
    live_price = price if price is not None else float("nan")
    live = dict(time=pd.Timestamp(session["time"]).floor(f"{interval}min"),
                open=live_price,high=live_price,low=live_price,close=live_price,volume=0)
    candles = pd.concat([closed,pd.DataFrame([live])],ignore_index=True)
    if strategy == "CRT":
        signal = evaluate_crt(candles)
        if len(closed)>=2:
            reference,trigger = closed.iloc[-2],closed.iloc[-1]
            signal["trigger_detail"] = f"15m reference range {reference['low']:,.2f}-{reference['high']:,.2f}; sweep candle low {trigger['low']:,.2f}, high {trigger['high']:,.2f}, close {trigger['close']:,.2f}."
        focus_label = "CRT Range"
    elif strategy == "Reversal":
        # Restart RSI after missing candles, rather than bridging an unknown gap.
        gaps = closed["time"].diff().ne(pd.Timedelta(minutes=15))
        if not closed.empty:
            candles = pd.concat([closed.iloc[gaps[gaps].index[-1]:],pd.DataFrame([live])],ignore_index=True)
        signal, candles = evaluate_reversal(candles,interval=15)
        if len(candles)>=3 and pd.notna(candles.iloc[-2]["rsi"]) and pd.notna(candles.iloc[-3]["rsi"]):
            signal["trigger_detail"] = f"Completed 15m RSI14: {candles.iloc[-3]['rsi']:.2f} to {candles.iloc[-2]['rsi']:.2f}; thresholds 30 / 70."
        focus_label = "RSI 30 / 70"
    elif strategy == "ORB":
        signal = evaluate_orb(source,price,session["time"],tick,read_orb_minutes(),interval=15)
        focus_label = "Opening range"
    elif strategy == "VWAP Reclaim":
        signal = evaluate_vwap(source,price,session["time"],tick,interval=15)
        focus_label = "Session VWAP"
    elif strategy == "EMA Pullback":
        signal = evaluate_ema_pullback(source,price,session["time"],tick,interval=15)
        focus_label = "EMA20 / EMA50"
    else:
        raise ValueError("Unknown strategy")
    setup_time = closed.iloc[-1]["time"].isoformat() if not closed.empty else None
    setup_id = f"{setup_time}|15m" + (f"|orb{signal['orb_minutes']}" if strategy == "ORB" else "")
    signal.update(setup_time=setup_time,signal_minutes=interval,exit_mode=MODE,tick_size=tick,
                  strategy_id=spec.id,entry_mode="CONFIRMED")
    signal.setdefault("trigger_detail",signal["reason"])
    latest_closed = pd.Timestamp(session["time"]).floor("15min")-pd.Timedelta(minutes=15)
    valid = not closed.empty and closed.iloc[-1]["time"] == latest_closed and price is not None
    if strategy == "CRT":
        valid = valid and len(closed)>=2 and closed.iloc[-1]["time"]-closed.iloc[-2]["time"] == pd.Timedelta(minutes=15)
    if not valid:
        signal.update(signal="WAIT",entry=None,stop=None,target=None,reason="Waiting for complete, current 15-minute signal candles.")
    fresh = not data.empty and 0 <= (session["time"]-data["time"].max()).total_seconds() <= 10
    def records(frame):
        return [{**bar,"time":bar["time"].isoformat(),"closed_at":(bar["time"]+pd.Timedelta(minutes=1)).isoformat()}
                for bar in frame.to_dict("records")]
    stop_bars = records(completed(source,session["time"]))
    signal = buffered_signal(signal,stop_bars,read_stop_minutes())
    # Existing CRT/Reversal signals retain the original tick-derived exit bars.
    management_bars = stop_bars
    if strategy in ("CRT","Reversal") and management_timeframe(symbol,strategy)==1:
        management_bars = records(minute_candles_from_ticks(data).iloc[:-1])
    signal = track_signal(symbol,strategy,signal,setup_id,allow_new and valid and session["is_open"] and fresh,management_bars)
    signal = session_signal(signal,session)
    if strategy in ("CRT","ORB"):
        focus_value = f"{format_price(signal.get('range_low'))} - {format_price(signal.get('range_high'))}"
        if strategy == "ORB":
            focus_label = f"Opening range / {signal.get('orb_minutes',read_orb_minutes())} min"
    elif strategy == "Reversal":
        focus_value = "-" if signal.get("rsi") is None else f"{signal['rsi']:.1f}"
    elif strategy == "VWAP Reclaim":
        focus_value = format_price(signal.get("vwap"))
    else:
        focus_value = f"{format_price(signal.get('ema20'))} / {format_price(signal.get('ema50'))}"
    return dict(signal=signal,timeframe=f"{interval} min",focus_label=focus_label,focus_value=focus_value,candles=candles)


def init_status(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS bot_monitor_status (symbol TEXT, strategy TEXT, record TEXT NOT NULL, PRIMARY KEY(symbol,strategy))")


def read_status():
    with closing(connect()) as conn:
        init_status(conn)
        conn.commit()
        return {(row[0], row[1]): json.loads(row[2]) for row in conn.execute("SELECT symbol,strategy,record FROM bot_monitor_status")}


def monitor_once():
    pairs = {(symbol, strategy) for symbol in SYMBOLS for strategy in STRATEGIES}
    pending = {(row["symbol"], row["strategy"]) for row in alert_history(10000) if row["status"] == "Active"}
    data = {symbol: price_history_for_symbol(symbol, hours=24) for symbol in {p[0] for p in pairs | pending}}
    minute_cache = {}
    for symbol, strategy in sorted(pairs | pending):
        try:
            extra = {}
            if strategy in STRATEGIES:
                if symbol not in minute_cache:
                    minute_cache[symbol] = chart_history(symbol)
                extra["candles_1m"] = minute_cache[symbol]
            # Quotes may arrive while history loads; compare against evaluation time.
            latest_tick = ticks_for_symbol(symbol, limit=1)
            if not latest_tick.empty:
                history = data[symbol]
                if history.empty:
                    data[symbol] = latest_tick
                elif latest_tick.iloc[-1]["id"] > history.iloc[-1]["id"]:
                    data[symbol] = pd.concat([history, latest_tick], ignore_index=True).tail(50000)
            session = market_session()
            result = evaluate_strategy_status(symbol, strategy, session, data[symbol], allow_new=(symbol, strategy) in pairs, **extra)
            result.pop("candles", None)
            result["updated_at"] = datetime.now(timezone.utc).isoformat()
            latest = data[symbol]["time"].max() if not data[symbol].empty else None
            result["feed_fresh"] = latest is not None and 0 <= (session["time"] - latest).total_seconds() <= 10
            result["quote_time"] = latest.isoformat() if latest is not None else None
            if "source_feed_fresh" in result:
                result["feed_fresh"] = result["source_feed_fresh"]
                result["quote_time"] = result["source_quote_time"]
            with closing(connect()) as conn:
                init_status(conn)
                conn.execute("INSERT OR REPLACE INTO bot_monitor_status VALUES (?,?,?)", (symbol, strategy, json.dumps(result, default=str)))
                signal = result["signal"]
                bot_audit.emit(f"monitor:{symbol}:{strategy}", "Strategy decision", f"{symbol} / {strategy} / {signal.get('signal')} / {signal.get('reason')}", conn=conn)
                bot_audit.emit(f"feed:{symbol}", "Feed status", f"{symbol}: {'fresh' if result['feed_fresh'] else 'stale' if session['is_open'] else 'session closed'}", severity="warning" if session["is_open"] and not result["feed_fresh"] else "info", notify=session["is_open"] and not result["feed_fresh"], conn=conn)
                conn.commit()
        except Exception as error:
            logging.warning("Monitor evaluation failed for %s %s (%s)", symbol, strategy, type(error).__name__)


def run_monitor(wakeup=None, executor_wakeup=None):
    wait = Event()
    while True:
        observed = wakeup.version() if wakeup is not None else None
        started = time.monotonic()
        try:
            monitor_once()
            if executor_wakeup is not None:
                executor_wakeup.notify()
        except Exception as error:
            logging.warning("Monitor cycle failed (%s)", type(error).__name__)
        if wakeup is None:
            wait.wait(2)
        else:
            # Capture generation before work so commits during evaluation aren't lost.
            wakeup.wait(observed, 2, not_before=started+.5)
