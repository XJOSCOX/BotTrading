from pathlib import Path

import streamlit.components.v1 as components
import pandas as pd
from reversal_strategy import add_rsi

from tv_lightweight_chart import candle_points_from_ticks


_chart = components.declare_component('live_candles', path=str(Path(__file__).parent / 'chart_component'))


def indicator_points(data, timeframe):
    points = candle_points_from_ticks(data, timeframe)
    if points:
        frame = pd.DataFrame(points)
        rsi = add_rsi(frame)['rsi']
        ema20 = frame['close'].ewm(span=20, adjust=False).mean()
        ema50 = frame['close'].ewm(span=50, adjust=False).mean()
        for point, value, fast, slow in zip(points, rsi, ema20, ema50):
            point['rsi'] = None if pd.isna(value) else float(value)
            point['ema20'] = float(fast)
            point['ema50'] = float(slow)
    return points


def render_live_candles(data, symbol, height=800, range_label='48H', timeframe='1min', candle_label='1 min', metrics=None):
    _chart(points=indicator_points(data, timeframe), symbol=symbol, height=height,
           range_label=range_label, timeframe=timeframe, candle_label=candle_label, metrics=metrics or [],
           key=f'live_chart_{symbol}_{timeframe}', default=None)
