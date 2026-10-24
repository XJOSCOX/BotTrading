"""Reactive entry-only circuit breaker; does not identify or predict news."""
import math
from contextlib import closing
from datetime import datetime, timezone

import pandas as pd

from goxtrade.data.chart_history import chart_history
from goxtrade.execution.contracts import contract_for_symbol
from goxtrade.data.live_store import connect
from goxtrade.data.price_ticks import TICK_SIZES, valid_price
from goxtrade.strategies.signal_candles import signal_candles

MICROS = {"NQ=F": "MNQ=F", "ES=F": "MES=F", "YM=F": "MYM=F"}
HOLD_SECONDS = 300


def true_ranges(bars):
    previous = bars["close"].shift()
    return pd.concat([bars["high"]-bars["low"], (bars["high"]-previous).abs(),
                      (bars["low"]-previous).abs()], axis=1).max(axis=1)


def assess(minutes, quote, symbol, contract_id, now, live_price=None):
    """Return (blocking reason, shock detected). Missing data never qualifies."""
    now = pd.Timestamp(now).tz_convert("UTC")
    if not quote or quote.get("contract_id") != contract_id:
        return "Volatility guard: matching micro quote unavailable", False
    for field in ("event_time", "received_at"):
        stamp = pd.to_datetime(quote.get(field), utc=True, errors="coerce")
        if pd.isna(stamp) or not 0 <= (now-stamp).total_seconds() <= 10:
            return "Volatility guard: micro quote stale", False
    bid, ask = (valid_price(symbol, quote.get(k)) for k in ("best_bid", "best_ask"))
    if bid is None or ask is None or bid <= 0 or ask <= bid:
        return "Volatility guard: valid two-sided micro quote required", False
    spread = (ask-bid)/TICK_SIZES[symbol]
    if spread > 4:
        return f"Volatility guard: micro spread {spread:.0f} ticks exceeds 4", True
    frame = minutes.copy()
    frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    frame = frame.loc[frame["time"] <= now.floor("min")].sort_values("time").drop_duplicates("time", keep="last")
    for field in ("open", "high", "low", "close"):
        frame[field] = pd.to_numeric(frame[field], errors="coerce")
    recent = frame.loc[frame["time"] >= now.floor("min")-pd.Timedelta(minutes=16)]
    expected = pd.date_range(now.floor("min")-pd.Timedelta(minutes=16), periods=16, freq="min")
    if not pd.DatetimeIndex(recent["time"]).intersection(expected).equals(expected):
        return "Volatility guard: incomplete recent minute history", False
    values = recent[["open", "high", "low", "close"]]
    if not values.map(lambda x: math.isfinite(x) and x > 0).all().all() or (recent["high"] < recent[["open","close","low"]].max(axis=1)).any() or (recent["low"] > recent[["open","close"]].min(axis=1)).any():
        return "Volatility guard: invalid candle data", False
    tr = true_ranges(recent)
    # Baseline excludes the most recent completed minute and the forming minute.
    baseline = float(tr.iloc[1:15].mean())
    floor = 4*TICK_SIZES[symbol]
    movement = float(tr.iloc[15:].max())
    if live_price is not None:
        price = valid_price(symbol, live_price)
        if price is None:
            return "Volatility guard: invalid live index price", False
        movement = max(movement, abs(price-float(recent.iloc[15]["close"])))
    if movement > 3*max(baseline, floor):
        return f"Volatility guard: 1m move {movement:.2f} exceeds 3x baseline {baseline:.2f}", True
    bars = signal_candles(frame, now, 15)
    expected_bar = now.floor("15min")-pd.Timedelta(minutes=15)
    if len(bars) < 16 or bars.iloc[-1]["time"] != expected_bar:
        return "Volatility guard: insufficient current 15m history", False
    sample = bars.tail(16)
    if not sample[["open","high","low","close"]].map(lambda x: math.isfinite(x) and x > 0).all().all():
        return "Volatility guard: invalid 15m history", False
    ranges = true_ranges(sample)
    baseline15 = float(ranges.iloc[1:-1].mean())
    if ranges.iloc[-1] > 2.5*max(baseline15, floor):
        return f"Volatility guard: 15m range {ranges.iloc[-1]:.2f} exceeds 2.5x baseline {baseline15:.2f}", True
    return None, False


def record_check(symbol, reason, shock, now):
    with closing(connect()) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS volatility_holds (symbol TEXT PRIMARY KEY, until REAL, reason TEXT)")
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        if shock:
            conn.execute("INSERT INTO volatility_holds VALUES (?,?,?) ON CONFLICT(symbol) DO UPDATE SET until=MAX(until,excluded.until),reason=excluded.reason",
                         (symbol, now.timestamp()+HOLD_SECONDS, reason))
        row = conn.execute("SELECT until,reason FROM volatility_holds WHERE symbol=?", (symbol,)).fetchone()
        conn.commit()
    if reason:
        return reason
    if row and row["until"] > now.timestamp():
        return f"Volatility cooldown: {math.ceil(row['until']-now.timestamp())}s remaining / {row['reason']}"
    return None


def entry_block(signal, contract_id, now=None):
    now = now or datetime.now(timezone.utc)
    symbol = signal["symbol"]
    try:
        with closing(connect()) as conn:
            row = conn.execute("SELECT * FROM latest_quotes WHERE symbol=?", (MICROS[symbol],)).fetchone()
            index_quote = conn.execute("SELECT price AS last_price,event_time,received_at FROM live_ticks WHERE symbol=? AND contract_id=? AND event_type='trade' AND price IS NOT NULL ORDER BY id DESC LIMIT 1",
                                       (symbol,contract_for_symbol(symbol))).fetchone()
        if not index_quote:
            return "Volatility guard: live index quote unavailable"
        for field in ("event_time", "received_at"):
            stamp = pd.to_datetime(index_quote[field], utc=True, errors="coerce")
            if pd.isna(stamp) or not 0 <= (pd.Timestamp(now)-stamp).total_seconds() <= 10:
                return "Volatility guard: live index quote stale"
        price = valid_price(symbol, index_quote["last_price"])
        if price is None:
            return "Volatility guard: live index price unavailable"
        reason, shock = assess(chart_history(symbol), dict(row) if row else None, symbol, contract_id, now, price)
        return record_check(symbol, reason, shock, now)
    except (ValueError, TypeError, KeyError, IndexError):
        return "Volatility guard: market data unavailable or invalid"
