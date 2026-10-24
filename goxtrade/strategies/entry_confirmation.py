"""15m setups await completed 5m structure and a fresh 1m break. Entry only."""
import math
from contextlib import closing
from datetime import datetime, timezone

import pandas as pd
from goxtrade.data.chart_history import chart_history
from goxtrade.execution.contracts import contract_for_symbol
from goxtrade.config.execution_target import PROFILE
from goxtrade.data.live_store import connect
from goxtrade.data.price_ticks import valid_price
from goxtrade.strategies.signal_candles import signal_candles


def window_open(signal, now=None):
    now = pd.Timestamp(now or datetime.now(timezone.utc))
    start = pd.to_datetime(signal.get("setup_time"), utc=True, errors="coerce")+pd.Timedelta(minutes=15)
    # Practice must have time to evaluate the first post-setup 5m close.
    seconds = 600 if PROFILE == "practice" else 300
    return bool(signal.get("signal_minutes") == 15 and pd.notna(start) and 0 <= (now-start).total_seconds() < seconds)


def evaluate(signal, minutes, price, now):
    def result(state, reason):
        return dict(state=state, reason=reason, price=price)
    if not window_open(signal, now) or signal.get("status") != "Active":
        return result("Cancelled", "15m setup expired or inactive")
    if signal.get("signal") not in ("LONG", "SHORT"):
        return result("Cancelled", "Invalid direction")
    now = pd.Timestamp(now).tz_convert("UTC")
    start = pd.Timestamp(signal["setup_time"])+pd.Timedelta(minutes=15)
    long = signal["signal"] == "LONG"
    level = signal.get("setup_invalidation",signal.get("initial_stop",signal.get("stop")))
    entry, target = signal.get("entry"),signal.get("target")
    if any(v is None or not math.isfinite(float(v)) for v in (price,level,entry,target)):
        return result("Waiting", "Entry levels or live price unavailable")
    one = signal_candles(minutes,now,1)
    five = signal_candles(minutes,now,5)
    if len(one)<3 or len(five)<2:
        return result("Waiting", "Need complete 1m and 5m candles")
    recent = one.tail(3)
    if (recent.iloc[-1]["time"] != now.floor("min")-pd.Timedelta(minutes=1)
            or not recent["time"].diff().iloc[1:].eq(pd.Timedelta(minutes=1)).all()
            or five.iloc[-1]["time"] != now.floor("5min")-pd.Timedelta(minutes=5)
            or five.iloc[-1]["time"]-five.iloc[-2]["time"] != pd.Timedelta(minutes=5)):
        return result("Waiting", "1m/5m history delayed or incomplete")
    for frame in (recent,five.tail(2)):
        values = frame[["open","high","low","close"]]
        if not values.map(lambda x: math.isfinite(x) and x>0).all().all():
            return result("Waiting", "Invalid confirmation candles")
    times = pd.to_datetime(minutes["time"],utc=True)
    after = minutes.loc[(times>=start) & (times<=now.floor("min"))]
    breached = (price<=level or (after["low"]<=level).any()) if long else (price>=level or (after["high"]>=level).any())
    if breached:
        return result("Cancelled", "Setup invalidation breached before entry")
    if (price>=target if long else price<=target):
        return result("Cancelled", "Reference target already reached before entry")
    risk = abs(entry-level)
    if risk<=0:
        return result("Cancelled", "Invalid setup risk")
    if abs(price-entry) > .5*risk:
        return result("Waiting" if PROFILE == "practice" else "Cancelled",
                      "Price moved more than 0.5 setup risk from the original entry")
    prev5, last5 = five.iloc[-2],five.iloc[-1]
    support = (last5["close"]>last5["open"] and last5["close"]>prev5["close"]) if long else (last5["close"]<last5["open"] and last5["close"]<prev5["close"])
    if not support:
        return result("Waiting", "5m candle body and close-to-close momentum do not support direction")
    prev,last = one.iloc[-2],one.iloc[-1]
    if last["time"] < start:
        return result("Waiting", "Awaiting a completed 1m trigger after the 15m setup")
    span = last["high"]-last["low"]
    trigger = (last["close"]>prev["high"] and last["close"]>last["open"] and last["close"]>=last["high"]-span/3 and price>=last["close"]) if long else (last["close"]<prev["low"] and last["close"]<last["open"] and last["close"]<=last["low"]+span/3 and price<=last["close"])
    if span<=0 or not trigger:
        return result("Waiting", "Awaiting 1m directional break, strong close and live-price follow-through")
    return result("Confirmed", f"5m directional body and momentum; 1m break at {last['time'].isoformat()}, close {last['close']:.2f}; live {price:.2f}")


def check(signal, now=None):
    now = now or datetime.now(timezone.utc)
    with closing(connect()) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS entry_confirmations (profile TEXT, alert_id INTEGER, state TEXT, reason TEXT, PRIMARY KEY(profile,alert_id))")
        row = conn.execute("SELECT state,reason FROM entry_confirmations WHERE profile=? AND alert_id=?",(PROFILE,signal["id"])).fetchone()
        if row and row["state"] == "Cancelled":
            return dict(row)
        tick = conn.execute("SELECT price,event_time,received_at FROM live_ticks WHERE symbol=? AND contract_id=? AND event_type='trade' AND price IS NOT NULL ORDER BY id DESC LIMIT 1",
                            (signal["symbol"],contract_for_symbol(signal["symbol"]))).fetchone()
        price = valid_price(signal["symbol"],tick["price"]) if tick else None
        fresh = tick and all(pd.notna(stamp:=pd.to_datetime(tick[k],utc=True,errors="coerce")) and 0<=(pd.Timestamp(now)-stamp).total_seconds()<=10 for k in ("event_time","received_at"))
        result = evaluate(signal,chart_history(signal["symbol"]),price,now) if fresh else dict(state="Waiting",reason="Fresh index trade required",price=None)
        conn.execute("INSERT OR REPLACE INTO entry_confirmations VALUES (?,?,?,?)",(PROFILE,signal["id"],result["state"],result["reason"]))
        conn.commit()
    return result
