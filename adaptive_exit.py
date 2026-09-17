"""Causal, watch-only exits. Levels are calculated from completed minute bars."""
from datetime import datetime

MODE = "structure-v1"


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


def update_exit(active, bars, tick):
    """Process only bars knowable at this tick; never loosen a protective stop."""
    now = timestamp(tick.get("event_time") or tick.get("received_at"))
    entered = timestamp(active.get("management_started_at"))
    if now is None or entered is None:
        return None
    long = active["signal"] == "LONG"
    lookback = active.get("structure_lookback", 3)
    confirmations = active.get("break_confirmations", 2)
    minutes = active.get("management_minutes", 1)
    for index, bar in enumerate(bars):
        closed = timestamp(bar["closed_at"])
        opened = timestamp(bar["time"])
        if closed is None or opened is None or closed > now or opened < entered:
            continue
        if closed <= active.get("managed_bar", entered):
            continue
        active["managed_bar"] = closed
        prior = bars[max(0, index - lookback):index]
        if len(prior) < lookback:
            continue
        # Gaps must not count as consecutive evidence across a session break.
        window = prior + [bar]
        if any(timestamp(b["time"]) - timestamp(a["time"]) != minutes*60 for a, b in zip(window, window[1:])):
            active["structure_breaks"] = 0
            continue
        boundary = min(b["low"] for b in prior) if long else max(b["high"] for b in prior)
        broken = bar["close"] < boundary if long else bar["close"] > boundary
        active["structure_breaks"] = active.get("structure_breaks", 0) + 1 if broken else 0
        active["exit_evidence"] = f"{minutes}m close {bar['close']:.2f}; prior {lookback}-bar {'low' if long else 'high'} {boundary:.2f}; breaks {active['structure_breaks']}/{confirmations}."
        if active["structure_breaks"] >= confirmations:
            active["management_status"] = "Structure break confirmed"
            return "Structure break"
        risk = abs(active["entry"] - active["initial_stop"])
        favorable = (bar["close"] - active["entry"]) * (1 if long else -1)
        if favorable >= risk * active.get("trail_start_r", 1.0) and risk > 0:
            active["trail_armed"] = True
        if active.get("trail_armed"):
            level = min(b["low"] for b in window[-lookback:]) if long else max(b["high"] for b in window[-lookback:])
            buffer = active.get("trail_buffer", active["tick_size"])
            level += -buffer if long else buffer
            import math
            level = (math.floor(level / active["tick_size"]) if long else math.ceil(level / active["tick_size"])) * active["tick_size"]
            active["stop"] = max(active["stop"], level) if long else min(active["stop"], level)
        active["management_status"] = "Trailing structure" if active.get("trail_armed") else "Holding / original stop"
    return None
