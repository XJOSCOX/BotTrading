from pathlib import Path

import streamlit.components.v1 as components
import pandas as pd
from goxtrade.market.chart_indicators import indicator_points

from goxtrade.ui.market.tv_lightweight_chart import candle_points_from_ticks


_chart = components.declare_component('live_candles', path=str(Path(__file__).parent / 'chart_component'))


def render_live_candles(data, symbol, height=800, range_label='48H', timeframe='1min', candle_label='1 min', metrics=None):
    _chart(points=indicator_points(data, timeframe), symbol=symbol, height=height,
           range_label=range_label, timeframe=timeframe, candle_label=candle_label, metrics=metrics or [],
           key=f'live_chart_{symbol}_{timeframe}', default=None)
