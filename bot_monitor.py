"""Background watch-only evaluation, independent of the Streamlit page."""
import json
import logging
import pandas as pd
from contextlib import closing
from datetime import datetime, timezone
from threading import Event

from crt_strategy import evaluate_crt, fifteen_minute_candles_from_ticks, minute_candles_from_ticks
from reversal_strategy import evaluate_reversal
from live_store import connect, price_history_for_symbol
from market_session import market_session, session_signal
from signal_lifecycle import track_signal, alert_history
from adaptive_exit import MODE
from stop_policy import buffered_signal
import bot_audit
from strategy_catalog import STRATEGIES, NEW_STRATEGIES
from continuation_strategies import evaluate_orb, evaluate_vwap, evaluate_ema_pullback, completed
from strategy_settings import read_orb_minutes, read_stop_minutes
from chart_history import chart_history

SYMBOLS = ("NQ=F", "ES=F", "YM=F")


def format_price(value):
    return "-" if value is None else f"{float(value):,.2f}"


def evaluate_strategy_status(symbol, strategy, session, data, allow_new=True, candles_1m=None) -> dict:
    if strategy in NEW_STRATEGIES:
        candles = chart_history(symbol) if candles_1m is None else candles_1m
        price = float(data.iloc[-1]["price"]) if not data.empty else None
        tick = 1.0 if symbol == "YM=F" else .25
        if strategy == "ORB":
            signal = evaluate_orb(candles, price, session["time"], tick, read_orb_minutes())
            focus_label = "Opening range"
        elif strategy == "VWAP Reclaim":
            signal = evaluate_vwap(candles, price, session["time"], tick)
            focus_label = "Session VWAP"
        else:
            signal = evaluate_ema_pullback(candles, price, session["time"], tick)
            focus_label = "EMA20 / EMA50"
        display_candles = candles
        timeframe = "1 min"
        focus_value = "-"
    elif strategy == "Reversal":
        candles = minute_candles_from_ticks(data)
        signal, display_candles = evaluate_reversal(candles)
        timeframe = "1 min"
        focus_label = "RSI 30 / 70"
        focus_value = "-" if signal.get("rsi") is None else f"{signal['rsi']:.1f}"
    elif strategy == "CRT":
        candles = fifteen_minute_candles_from_ticks(data)
        signal = evaluate_crt(candles)
        display_candles = candles
        timeframe = "15 min"
        focus_label = "CRT Range"
        if signal["range_high"] is None or signal["range_low"] is None:
            focus_value = "-"
        else:
            focus_value = f"{format_price(signal['range_low'])} - {format_price(signal['range_high'])}"
    else:
        raise ValueError("Unknown strategy")
    if strategy in NEW_STRATEGIES:
        finished = completed(candles,session["time"])
        setup_time = finished.iloc[-1]["time"].isoformat() if not finished.empty else None
        setup_id = f"{setup_time}|orb{signal['orb_minutes']}" if strategy == "ORB" else setup_time
    else:
        setup_id = setup_time = candles.iloc[-2]["time"].isoformat() if len(candles) >= 2 else None
    signal['setup_time'] = setup_time
    signal.setdefault('trigger_detail', signal['reason'])
    if strategy not in NEW_STRATEGIES and len(candles) >= 3:
        trigger = candles.iloc[-2]
        if strategy == 'CRT':
            reference = candles.iloc[-3]
            signal['trigger_detail'] = (
                f"Reference range {format_price(reference['low'])} - {format_price(reference['high'])}. "
                f"Signal candle low {format_price(trigger['low'])}, high {format_price(trigger['high'])}, "
                f"close {format_price(trigger['close'])}."
            )
        elif 'rsi' in display_candles:
            prior_rsi = display_candles.iloc[-3]['rsi']
            current_rsi = display_candles.iloc[-2]['rsi']
            import pandas as pd
            if pd.notna(prior_rsi) and pd.notna(current_rsi):
                signal['trigger_detail'] = f"Completed-candle RSI: {prior_rsi:.2f} to {current_rsi:.2f}. Thresholds: 30 / 70."
    fresh = not data.empty and 0 <= (session["time"] - data["time"].max()).total_seconds() <= 10
    signal["exit_mode"] = MODE
    signal["tick_size"] = 1.0 if symbol == "YM=F" else 0.25
    minute_bars = candles if strategy in NEW_STRATEGIES else minute_candles_from_ticks(data)
    management_bars = []
    finished = completed(minute_bars,session["time"]) if strategy in NEW_STRATEGIES else minute_bars.iloc[:-1]
    if strategy in NEW_STRATEGIES:
        import pandas as pd
        latest_closed = pd.Timestamp(session["time"]).floor("min")-pd.Timedelta(minutes=1)
        if finished.empty or finished.iloc[-1]["time"] != latest_closed or price is None:
            allow_new = False
            signal.update(signal="WAIT",entry=None,stop=None,target=None,reason="Waiting for a current completed minute.")
    for bar in finished.to_dict("records"):
        import pandas as pd
        management_bars.append({**bar, "time": bar["time"].isoformat(),
                                "closed_at": (bar["time"] + pd.Timedelta(minutes=1)).isoformat()})
    import pandas as pd
    stop_candles = chart_history(symbol) if candles_1m is None else candles_1m
    stop_bars = [{**bar,"time":bar["time"].isoformat(),"closed_at":(bar["time"]+pd.Timedelta(minutes=1)).isoformat()}
                 for bar in completed(stop_candles,session["time"]).to_dict("records")]
    signal = buffered_signal(signal, stop_bars, read_stop_minutes())
    # Legacy signals retain their original minute-bar source and exit policy.
    from signal_lifecycle import management_timeframe
    if management_timeframe(symbol,strategy) > 1:
        management_bars = stop_bars
    signal = track_signal(symbol, strategy, signal, setup_id, allow_new and session["is_open"] and fresh, management_bars)
    signal = session_signal(signal, session)
    if strategy == "CRT":
        focus_value = f"{format_price(signal['range_low'])} - {format_price(signal['range_high'])}"
    elif strategy == "Reversal":
        focus_value = "-" if signal.get("rsi") is None else f"{signal['rsi']:.1f}"
    elif strategy == "ORB":
        focus_label = f"Opening range / {signal.get('orb_minutes',read_orb_minutes())} min"
        focus_value = f"{format_price(signal.get('range_low'))} - {format_price(signal.get('range_high'))}"
    elif strategy == "VWAP Reclaim":
        focus_value = format_price(signal.get("vwap"))
    else:
        focus_value = f"{format_price(signal.get('ema20'))} / {format_price(signal.get('ema50'))}"
    return dict(signal=signal, timeframe=timeframe, focus_label=focus_label,
                focus_value=focus_value, candles=display_candles)


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
            session = market_session()
            result = evaluate_strategy_status(symbol, strategy, session, data[symbol], allow_new=(symbol, strategy) in pairs, **extra)
            result.pop("candles", None)
            result["updated_at"] = datetime.now(timezone.utc).isoformat()
            latest = data[symbol]["time"].max() if not data[symbol].empty else None
            result["feed_fresh"] = latest is not None and 0 <= (session["time"] - latest).total_seconds() <= 10
            result["quote_time"] = latest.isoformat() if latest is not None else None
            with closing(connect()) as conn:
                init_status(conn)
                conn.execute("INSERT OR REPLACE INTO bot_monitor_status VALUES (?,?,?)", (symbol, strategy, json.dumps(result, default=str)))
                signal = result["signal"]
                bot_audit.emit(f"monitor:{symbol}:{strategy}", "Strategy decision", f"{symbol} / {strategy} / {signal.get('signal')} / {signal.get('reason')}", conn=conn)
                bot_audit.emit(f"feed:{symbol}", "Feed status", f"{symbol}: {'fresh' if result['feed_fresh'] else 'stale' if session['is_open'] else 'session closed'}", severity="warning" if session["is_open"] and not result["feed_fresh"] else "info", notify=session["is_open"] and not result["feed_fresh"], conn=conn)
                conn.commit()
        except Exception as error:
            logging.warning("Monitor evaluation failed for %s %s (%s)", symbol, strategy, type(error).__name__)


def run_monitor():
    wait = Event()
    while True:
        try:
            monitor_once()
        except Exception as error:
            logging.warning("Monitor cycle failed (%s)", type(error).__name__)
        wait.wait(2)
