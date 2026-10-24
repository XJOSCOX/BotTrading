"""Strategy-specific initial levels; existing positions keep this frozen snapshot."""
import math

from goxtrade.market.instruments import round_tick
from goxtrade.strategies.adaptive_exit import MODE
from goxtrade.strategies.stop_policy import buffered_signal


def risk_levels(direction, entry, frame, minutes, config, tick):
    long = direction == "LONG"
    entry = round_tick(entry, tick, up=long)
    last = frame.iloc[-1]
    swing = frame.tail(config.swing_bars)
    level = float(swing["low"].min() if long else swing["high"].max())
    atr = float(last["atr"])
    if config.stop_method == "atr":
        if not math.isfinite(atr) or atr <= 0:
            raise ValueError("ATR stop requires initialized volatility")
        level = entry + (-1 if long else 1) * config.atr_multiple * atr
    elif config.stop_method == "fixed":
        level = entry + (-1 if long else 1) * config.fixed_stop_ticks * tick
    stop = round_tick(level, tick, up=not long)
    if (entry - stop) * (1 if long else -1) <= 0:
        raise ValueError("Strategy stop is already invalidated")
    result = dict(signal=direction, entry=entry, stop=stop, target=entry + (entry-stop) * config.reward_risk,
                  tick_size=tick, setup_invalidation=stop, management_minutes=config.management_minutes)
    if config.stop_method == "buffered":
        rows = [{**row, "time": row["time"].isoformat()} for row in minutes.to_dict("records")]
        result = buffered_signal(result, rows, config.management_minutes)
        if result["signal"] == "WAIT":
            raise ValueError(result["reason"])
        stop = result["stop"]
    risk = abs(entry-stop)
    target = round_tick(entry + (risk * config.reward_risk if long else -risk * config.reward_risk), tick, up=long)
    if not (0 < stop < entry < target if long else 0 < target < entry < stop):
        raise ValueError("Invalid rounded stop, entry, or target")
    result.update(stop=stop, target=target, initial_stop=stop, initial_risk_points=risk,
                  actual_reward_risk=abs(target-entry)/risk,
                  exit_mode=MODE if config.management_method == "adaptive" else config.management_method,
                  trail_start_r=config.trail_start_r, trail_ticks=config.trail_ticks,
                  breakeven_r=config.breakeven_r, risk_config=config.to_dict())
    return result
