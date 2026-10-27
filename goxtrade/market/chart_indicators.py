"""Shared price-chart indicators, independent of either UI runtime."""
import pandas as pd
import math
from goxtrade.strategies.reversal_strategy import add_rsi
from goxtrade.ui.market.tv_lightweight_chart import candle_points_from_ticks


def indicator_points(data, timeframe):
    points = candle_points_from_ticks(data, timeframe)
    if points:
        frame = pd.DataFrame(points)
        rsi = add_rsi(frame)["rsi"]
        fast = frame["close"].ewm(span=20, adjust=False).mean()
        slow = frame["close"].ewm(span=50, adjust=False).mean()
        for point, value, ema20, ema50 in zip(points, rsi, fast, slow):
            point.update(rsi=None if pd.isna(value) else float(value), ema20=float(ema20), ema50=float(ema50))
        weighted, total, previous_session, valid = 0.0, 0.0, None, False
        previous_time = None
        interval_seconds = pd.tseries.frequencies.to_offset(timeframe).nanos / 1_000_000_000
        for point in points:
            local = pd.Timestamp(point["time"], unit="s", tz="UTC").tz_convert("America/Chicago")
            day = local.date() if local.hour >= 17 else (local - pd.Timedelta(days=1)).date()
            anchor = pd.Timestamp(f"{day} 17:00", tz="America/Chicago")
            if anchor != previous_session:
                weighted, total = 0.0, 0.0
                valid = local == anchor
                previous_session = anchor
            elif previous_time is not None and point["time"] - previous_time != interval_seconds:
                valid = False
            previous_time = point["time"]
            volume = point["volume"]
            valid = valid and volume is not None and math.isfinite(volume) and volume >= 0
            if valid:
                weighted += (point["high"] + point["low"] + point["close"]) / 3 * volume
                total += volume
            point["vwap"] = weighted / total if valid and total > 0 else None
    return points
