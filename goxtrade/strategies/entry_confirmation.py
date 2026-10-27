"""15m setups await completed 5m structure and a fresh 1m break. Entry only."""
import math
import os
from contextlib import closing
from datetime import datetime, timezone

import pandas as pd
from goxtrade.execution.contracts import contract_for_symbol
from goxtrade.data.live_store import connect
from goxtrade.data.price_ticks import valid_price
from goxtrade.strategies.signal_candles import signal_candles

PROFILE=os.getenv("GOX_EXECUTION_PROFILE","practice")


def chart_history(*args,**kwargs):
    # Live-only retrieval stays lazy: pure confirmation can run without transport.
    from goxtrade.data.chart_history import chart_history as retrieve
    return retrieve(*args,**kwargs)


def window_open(signal, now=None, *, profile=None):
    now = pd.Timestamp(now or datetime.now(timezone.utc))
    if signal.get("entry_policy") in ("indicator-event-v1","previous-box-v1"):
        start = pd.to_datetime(signal.get("confirmed_at") if signal.get("entry_mode") == "CONFIRMED" else signal.get("detected_at"), utc=True, errors="coerce")
        seconds = signal.get("entry_window_seconds", 90)
        return bool(pd.notna(start) and isinstance(seconds, (int, float)) and 0 < seconds <= 600
                    and 0 <= (now-start).total_seconds() < seconds)
    start = pd.to_datetime(signal.get("setup_time"), utc=True, errors="coerce")+pd.Timedelta(minutes=15)
    # Practice must have time to evaluate the first post-setup 5m close.
    seconds = 600 if (profile or PROFILE) in ("practice","research") else 300
    return bool(signal.get("signal_minutes") == 15 and pd.notna(start) and 0 <= (now-start).total_seconds() < seconds)


def evaluate(signal, minutes, price, now, *, profile=None):
    if signal.get("entry_policy") == "previous-box-v1":
        from goxtrade.strategies.previous_day_box import evaluate_previous_day_box, validate_entry
        from goxtrade.strategies.previous_day_box_config import PreviousDayBoxConfig
        reason = validate_entry(signal,price,now,minutes.attrs.get("contract_id"))
        if signal.get("status")!="Active": reason = "Box signal is inactive"
        if reason: return dict(state="Cancelled",reason=reason,price=price)
        config = PreviousDayBoxConfig.from_dict(signal["config_snapshot"])
        current,_ = evaluate_previous_day_box(minutes,price,now,config,symbol=signal["symbol"],contract_id=signal["source_contract"],quote_time=now,box_override=signal["box"])
        if current.get("unique_setup_id") != signal.get("unique_setup_id"):
            return dict(state="Cancelled",reason="Original box confirmation no longer valid: "+current["reason"],price=price)
        return dict(state="Confirmed",reason="Original completed box reversal revalidated at executable price; stop retained",price=price,history_complete=True)
    if signal.get("entry_policy") == "indicator-event-v1":
        return evaluate_indicator_entry(signal, minutes, price, now)
    history_complete = False
    def result(state, reason):
        return dict(state=state, reason=reason, price=price, history_complete=history_complete)
    if not window_open(signal, now,profile=profile) or signal.get("status") != "Active":
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
    history_complete = True
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
        return result("Waiting" if (profile or PROFILE) in ("practice","research") else "Cancelled",
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


def evaluate_indicator_entry(signal, minutes, price, now):
    from goxtrade.strategies.vwap_ema_config import VwapEmaConfig
    from goxtrade.strategies.vwap_ema_indicators import indicator_frame
    from goxtrade.strategies.vwap_ema_cross import optional_filters
    from goxtrade.market.instruments import instrument
    history_complete = False
    def result(state, reason):
        return dict(state=state, reason=reason, price=price, history_complete=history_complete)
    if signal.get("status") != "Active" or not window_open(signal, now):
        return result("Cancelled", "Indicator event expired or inactive")
    if signal.get("signal") not in ("LONG", "SHORT"):
        return result("Cancelled", "Invalid indicator direction")
    config = VwapEmaConfig.from_dict(signal.get("config_snapshot"))
    if minutes.attrs.get("contract_id") != signal.get("source_contract"):
        return result("Cancelled", "Indicator history contract no longer matches the detected setup")
    if any(value is None or not math.isfinite(float(value)) for value in (price, signal.get("stop"), signal.get("target"))):
        return result("Waiting", "Valid executable price and protective levels are required")
    long = signal["signal"] == "LONG"
    if (price <= signal["stop"] if long else price >= signal["stop"]):
        return result("Cancelled", "Strategy protective stop invalidated before entry")
    if (signal.get("_post_detection_low", price) <= signal["stop"] if long else signal.get("_post_detection_high", price) >= signal["stop"]):
        return result("Cancelled", "A post-detection trade breached the protective stop")
    if (price >= signal["target"] if long else price <= signal["target"]):
        return result("Cancelled", "Strategy reference target reached before entry")
    try:
        frame = indicator_frame(minutes, now, config, signal.get("_validation_sequence"))
        if len(frame) < 2 or not frame.iloc[-1]["coverage"]:
            return result("Waiting", "Current complete session data is unavailable")
        last, prior = frame.iloc[-1], frame.iloc[-2]
        if pd.isna(last["gap"]) or last["warmup"] < config.warmup_bars:
            return result("Waiting", "Indicators are not initialized")
        history_complete = True
        if config.entry_mode == "CONFIRMED":
            cross = prior["gap"] <= 0 < last["gap"] if long else prior["gap"] >= 0 > last["gap"]
            if last["time"] != pd.Timestamp(signal["setup_time"]) or not cross:
                return result("Cancelled", "The original completed crossover is no longer current")
        elif config.entry_mode == "REALTIME":
            if not last["provisional"] or not (last["gap"] > 0 if long else last["gap"] < 0):
                return result("Cancelled", "The provisional crossover reversed before submission")
        else:
            approaching_side = last["gap"] < 0 if long else last["gap"] > 0
            sign = 1 if long else -1
            supporting = ((last["ema"]-prior["ema"])*sign > config.anticipation_min_slope_ticks*instrument(signal["symbol"]).tick_size
                          and (last["close"]-prior["close"])*sign > 0)
            if (not last["provisional"] or not approaching_side or not supporting
                    or abs(last["gap"]) > abs(signal.get("indicator_distance", 0))
                    or abs(last["gap"]) > config.anticipation_distance_ticks*instrument(signal["symbol"]).tick_size):
                return result("Cancelled", "Anticipatory conditions changed; no conversion into a confirmed signal")
        checks = optional_filters(frame, signal["signal"], price, now, config, instrument(signal["symbol"]).tick_size)
        failed = [name for name, value in checks.items() if value == "failed"]
        if failed:
            return result("Waiting", "Current strategy filters failed: " + ", ".join(failed))
    except (ValueError, KeyError, TypeError) as error:
        return result("Waiting", f"Strategy validation data unavailable: {error}")
    return result("Confirmed", f"{config.entry_mode} indicator event revalidated at current trade price {price:.2f}; original strategy stop retained")


def check(signal, now=None):
    now = now or datetime.now(timezone.utc)
    source_symbol = (signal.get("reference_symbol") or signal["symbol"]) if signal.get("entry_policy")=="indicator-event-v1" else signal["symbol"]
    if signal.get("entry_policy") in ("indicator-event-v1","previous-box-v1"):
        from goxtrade.market.calendar_guard import entry_block
        blocked = entry_block(now)
        if blocked:
            return dict(state="Waiting", reason=blocked, price=None)
    with closing(connect()) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS entry_confirmations (profile TEXT, alert_id INTEGER, state TEXT, reason TEXT, PRIMARY KEY(profile,alert_id))")
        row = conn.execute("SELECT state,reason FROM entry_confirmations WHERE profile=? AND alert_id=?",(PROFILE,signal["id"])).fetchone()
        if row and row["state"] == "Cancelled":
            return dict(row)
        tick = conn.execute("SELECT price,event_time,received_at FROM live_ticks WHERE symbol=? AND contract_id=? AND event_type='trade' AND price IS NOT NULL ORDER BY id DESC LIMIT 1",
                            (source_symbol,contract_for_symbol(source_symbol))).fetchone()
        price = valid_price(source_symbol,tick["price"]) if tick else None
        fresh = tick and all(pd.notna(stamp:=pd.to_datetime(tick[k],utc=True,errors="coerce")) and 0<=(pd.Timestamp(now)-stamp).total_seconds()<=10 for k in ("event_time","received_at"))
        source = None
        if fresh and signal.get("entry_policy") in ("indicator-event-v1","previous-box-v1"):
            from goxtrade.data.strategy_history import load_strategy_minutes, latest_trade
            contract = contract_for_symbol(source_symbol)
            source = load_strategy_minutes(source_symbol, contract, now, hours=24*16 if signal.get("strategy_id")=="previous_day_box" else 72)
            last = latest_trade(source_symbol, contract)
            bounds = conn.execute("SELECT MIN(price),MAX(price) FROM live_ticks WHERE symbol=? AND contract_id=? AND event_type='trade' AND id>? AND price>0",
                                  (source_symbol, contract, signal.get("detection_sequence") or 0)).fetchone()
            signal = {**signal, "_validation_sequence": last["id"] if last else None,
                      "_post_detection_low": bounds[0] if bounds[0] is not None else price,
                      "_post_detection_high": bounds[1] if bounds[1] is not None else price}
        result = evaluate(signal,source if source is not None else chart_history(signal["symbol"]),price,now) if fresh else dict(state="Waiting",reason="Fresh index trade required",price=None)
        conn.execute("INSERT OR REPLACE INTO entry_confirmations VALUES (?,?,?,?)",(PROFILE,signal["id"],result["state"],result["reason"]))
        conn.commit()
    return result
