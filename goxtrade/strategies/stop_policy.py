"""Buffered initial stops using only contiguous completed one-minute bars."""
import math
from datetime import datetime, timezone


def aggregate_minutes(bars, minutes):
    """Aggregate complete UTC-aligned buckets only; never fill missing minutes."""
    if minutes == 1:
        return bars
    buckets = {}
    for bar in bars:
        stamp = datetime.fromisoformat(bar["time"]).timestamp()
        bucket = int(stamp // (minutes*60)) * minutes*60
        buckets.setdefault(bucket,{})[stamp] = bar
    result = []
    for start, values in sorted(buckets.items()):
        expected = [start+i*60 for i in range(minutes)]
        if sorted(values) != expected:
            continue
        rows = [values[t] for t in expected]
        result.append(dict(time=datetime.fromtimestamp(start,timezone.utc).isoformat(),
                           closed_at=datetime.fromtimestamp(start+minutes*60,timezone.utc).isoformat(),
                           high=max(b["high"] for b in rows),low=min(b["low"] for b in rows),close=rows[-1]["close"]))
    return result


def buffered_signal(signal, bars, minutes=1):
    result = dict(signal)
    if signal.get("signal") not in ("LONG", "SHORT"):
        return result
    latest_close = max((datetime.fromisoformat(b["time"]).timestamp()+60 for b in bars),default=0)
    bars = aggregate_minutes(bars, minutes)
    window = bars[-15:]
    valid = len(window) == 15 and all(
        (datetime.fromisoformat(b["time"]) - datetime.fromisoformat(a["time"])).total_seconds() == minutes*60
        for a, b in zip(window, window[1:]))
    if minutes > 1 and window:
        expected = (int(latest_close // (minutes*60))-1)*minutes*60
        valid = valid and datetime.fromisoformat(window[-1]["time"]).timestamp() == expected
    if not valid:
        return {**result, "signal": "WAIT", "entry": None, "stop": None, "target": None,
                "reason": f"Waiting for 15 contiguous completed {minutes}-minute candles for stop sizing."}
    ranges = [max(b["high"]-b["low"], abs(b["high"]-a["close"]), abs(b["low"]-a["close"]))
              for a, b in zip(window, window[1:])]
    atr = sum(ranges) / 14
    if not math.isfinite(atr) or atr <= 0:
        return {**result, "signal": "WAIT", "entry": None, "stop": None, "target": None,
                "reason": "Waiting for valid volatility data."}
    tick = signal["tick_size"]
    buffer = max(tick, atr * .5)
    entry, invalidation = signal["entry"], signal["stop"]
    long = signal["signal"] == "LONG"
    if minutes > 1:
        swing = min(b["low"] for b in window[-3:]) if long else max(b["high"] for b in window[-3:])
        invalidation = min(invalidation,swing) if long else max(invalidation,swing)
    level = min(invalidation-buffer, entry-max(atr, 4*tick)) if long else max(invalidation+buffer, entry+max(atr, 4*tick))
    stop = (math.floor(level/tick) if long else math.ceil(level/tick)) * tick
    result.update(stop=stop, setup_invalidation=invalidation, stop_atr=atr,
                  trail_start_r=1.5, trail_buffer=buffer, stop_policy="buffered-v2", management_minutes=minutes)
    result["trigger_detail"] = result.get("trigger_detail", "") + f" Buffered stop {stop:.2f}; invalidation {invalidation:.2f}; {minutes}m ATR(14) {atr:.2f}; trail starts at 1.5R."
    return result
