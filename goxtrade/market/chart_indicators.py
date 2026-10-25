"""Shared price-chart indicators, independent of either UI runtime."""
import pandas as pd
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
    return points
