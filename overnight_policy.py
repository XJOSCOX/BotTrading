"""Entry-only overnight filters. Thresholds require forward testing, not profit guarantees."""
import math
from contextlib import closing
from datetime import datetime, time
import pandas as pd
from market_session import CENTRAL, market_session
from signal_candles import signal_candles
from live_store import connect
from chart_history import chart_history

MICRO_SYMBOLS = ("MNQ=F","MES=F","MYM=F")


def overnight(now=None):
    local = (now or datetime.now(CENTRAL)).astimezone(CENTRAL)
    return local.time() >= time(17) or local.time() < time(8,30)


def cooldown_seconds(configured, now=None):
    return max(configured,900) if overnight(now) else configured


def quantity(configured, now=None):
    return min(configured,1) if overnight(now) else configured


def valid_trend_history(bars, expected):
    """Allow scheduled closures, but never bridge missing open-market candles."""
    if len(bars) < 52:
        return False
    stamps = pd.to_datetime(bars.tail(52)["time"], utc=True, errors="coerce")
    if (stamps.isna().any() or not stamps.is_monotonic_increasing or stamps.duplicated().any()
            or not stamps.eq(stamps.dt.floor("15min")).all() or stamps.iloc[-1] != expected):
        return False
    expected_stamps = pd.date_range(stamps.iloc[0], expected, freq="15min")
    return all(not market_session(stamp.to_pydatetime())["is_open"]
               for stamp in expected_stamps.difference(pd.DatetimeIndex(stamps)))


def evaluate(signal, history, enabled, bars, quote, contract_id, now):
    if not overnight(now):
        return None
    if signal.get("signal") not in ("LONG", "SHORT"):
        return "Overnight: invalid signal direction"
    expected = pd.Timestamp(now).tz_convert("UTC").floor("15min")-pd.Timedelta(minutes=15)
    if (signal.get("status") != "Active" or signal.get("strategy") not in enabled
            or signal.get("signal_minutes") != 15
            or pd.to_datetime(signal.get("setup_time"),utc=True,errors="coerce") != expected):
        return "Overnight: need an enabled strategy on the current completed 15m candle"
    if any(row.get("status") == "Active" and row.get("symbol") == signal.get("symbol")
           and row.get("strategy") in enabled and row.get("signal") in ("LONG", "SHORT")
           and row["signal"] != signal["signal"] for row in history):
        return "Overnight: conflicting active strategy direction"
    if not valid_trend_history(bars, expected):
        return "Overnight: need 52 current 15m candles without missing open-market bars"
    closes = pd.to_numeric(bars.tail(52)["close"],errors="coerce")
    if not closes.map(lambda x: math.isfinite(x) and x>0).all():
        return "Overnight: invalid trend data"
    fast,slow = closes.ewm(span=20,adjust=False).mean(),closes.ewm(span=50,adjust=False).mean()
    long = signal["signal"]=="LONG"
    aligned = (fast.iloc[-1]>slow.iloc[-1] and slow.iloc[-1]>slow.iloc[-2] and closes.iloc[-1]>fast.iloc[-1]) if long else (fast.iloc[-1]<slow.iloc[-1] and slow.iloc[-1]<slow.iloc[-2] and closes.iloc[-1]<fast.iloc[-1])
    if not aligned:
        return "Overnight: 15m close, EMA20/50 and EMA50 slope do not confirm direction"
    volume = pd.to_numeric(bars.tail(21)["volume"],errors="coerce")
    if not volume.map(lambda x: math.isfinite(x) and x>0).all():
        return "Overnight: missing or invalid 15m trade volume"
    median = float(volume.iloc[:-1].median())
    if volume.iloc[-1]<median:
        return f"Overnight: volume {volume.iloc[-1]:.0f} below prior 20-candle median {median:.0f}"
    if not quote or quote.get("contract_id")!=contract_id:
        return "Overnight: matching micro-contract bid/ask unavailable"
    for field in ("event_time","received_at"):
        stamp = pd.to_datetime(quote.get(field),utc=True,errors="coerce")
        if pd.isna(stamp) or not 0 <= (pd.Timestamp(now)-stamp).total_seconds() <= 10:
            return "Overnight: micro-contract bid/ask is stale"
    bid,ask = quote.get("best_bid"),quote.get("best_ask")
    tick = 1.0 if signal["symbol"]=="YM=F" else .25
    if any(not isinstance(v,(float,int)) or not math.isfinite(v) or v<=0 for v in (bid,ask)) or ask<=bid:
        return "Overnight: invalid or crossed micro-contract bid/ask"
    if any(abs(v/tick-round(v/tick))>1e-6 for v in (bid,ask)) or ask-bid>2*tick+1e-8:
        return "Overnight: micro-contract spread exceeds two ticks or is off tick grid"
    return None


def entry_block(signal, history, enabled, positions, orders, jobs, contract_id, own_alert=None, now=None):
    now = now or datetime.now(CENTRAL)
    if not overnight(now):
        return None
    if positions or orders or any(j.get("alert_id")!=own_alert and j.get("state") not in ("Closed","Rejected") for j in jobs):
        return "Overnight: one position at a time; wait for positions and orders to clear"
    micro = {"NQ=F":"MNQ=F","ES=F":"MES=F","YM=F":"MYM=F"}[signal["symbol"]]
    with closing(connect()) as conn:
        row = conn.execute("SELECT * FROM latest_quotes WHERE symbol=?",(micro,)).fetchone()
    bars = signal_candles(chart_history(signal["symbol"]),now,15)
    return evaluate(signal,history,enabled,bars,dict(row) if row else None,contract_id,now)
