from __future__ import annotations

import json

import pandas as pd


def candle_points_from_ticks(data: pd.DataFrame, timeframe: str = "min") -> list[dict]:
    if data.empty:
        return []
    if {"open", "high", "low", "close"}.issubset(data.columns):
        data = data.sort_values('time').copy()
        data['bucket'] = pd.to_datetime(data['time'], utc=True).dt.floor(timeframe)
        data['volume'] = pd.to_numeric(data.get('volume', pd.Series(index=data.index, dtype=float)), errors='coerce')
        data = data.groupby('bucket', as_index=False).agg(
            open=('open', 'first'), high=('high', 'max'), low=('low', 'min'), close=('close', 'last'),
            volume=('volume', lambda values: values.sum(min_count=1))
        ).rename(columns={'bucket': 'time'})
        return [{"time": int(row.time.timestamp()), "open": float(row.open),
                 "high": float(row.high), "low": float(row.low), "close": float(row.close),
                 "volume": None if pd.isna(row.volume) else float(row.volume)}
                for row in data.itertuples()]
    frame = data.dropna(subset=["time", "price"]).copy()
    if frame.empty:
        return []
    frame["bucket"] = pd.to_datetime(frame["time"], utc=True).dt.floor(timeframe)
    frame['trade_volume'] = pd.to_numeric(frame.get('volume', 0), errors='coerce')
    frame['trade_volume'] = frame['trade_volume'].where(frame.get('event_type', pd.Series('', index=frame.index)).eq('trade'), 0)
    candles = frame.groupby("bucket", as_index=False).agg(
        open=("price", "first"),
        high=("price", "max"),
        low=("price", "min"),
        close=("price", "last"),
        volume=('trade_volume', 'sum'),
    )
    candles["epoch"] = (candles["bucket"].astype("int64") // 1_000_000_000).astype(int)
    return [
        {
            "time": int(row.epoch),
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "volume": float(row.volume),
        }
        for row in candles.itertuples()
    ]


def lightweight_chart_html(
    data: pd.DataFrame,
    symbol: str,
    timeframe: str = "min",
    label: str = "1m candles",
    levels: dict | None = None,
    height: int = 620,
) -> str:
    points = candle_points_from_ticks(data, timeframe=timeframe)
    payload = json.dumps(points)
    title = json.dumps(symbol)
    chart_label = json.dumps(label)
    level_payload = json.dumps(levels or {})
    return f"""
    <div id="chart-root" style="height:{height}px;width:100%;background:#0f131a;border:1px solid #242a34;border-radius:8px;"></div>
    <script src="https://unpkg.com/lightweight-charts@4.2.3/dist/lightweight-charts.standalone.production.js"></script>
    <script>
      const data = {payload};
      const symbol = {title};
      const label = {chart_label};
      const levels = {level_payload};
      const root = document.getElementById('chart-root');
      root.innerHTML = '';
      const ctTime = new Intl.DateTimeFormat('en-US', {{
        timeZone: 'America/Chicago', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'
      }});
      const ctDate = new Intl.DateTimeFormat('en-US', {{
        timeZone: 'America/Chicago', month: 'short', day: 'numeric'
      }});

      const chart = LightweightCharts.createChart(root, {{
        autoSize: true,
        localization: {{
          timeFormatter: time => ctDate.format(new Date(time * 1000)) + ' ' + ctTime.format(new Date(time * 1000)) + ' CT',
        }},
        layout: {{
          background: {{ type: 'solid', color: '#0f131a' }},
          textColor: '#d6dce5',
          fontFamily: 'Inter, Segoe UI, sans-serif',
        }},
        grid: {{
          vertLines: {{ color: '#1f2630' }},
          horzLines: {{ color: '#1f2630' }},
        }},
        rightPriceScale: {{
          borderColor: '#303846',
        }},
        timeScale: {{
          borderColor: '#303846',
          timeVisible: true,
          secondsVisible: false,
          tickMarkFormatter: (time, type) => type <= 2
            ? ctDate.format(new Date(time * 1000))
            : ctTime.format(new Date(time * 1000)),
        }},
        crosshair: {{
          mode: LightweightCharts.CrosshairMode.Normal,
        }},
      }});

      const series = chart.addCandlestickSeries({{
        upColor: '#22c55e',
        downColor: '#ef4444',
        wickUpColor: '#22c55e',
        wickDownColor: '#ef4444',
        borderVisible: false,
        priceLineVisible: true,
        lastValueVisible: true,
      }});

      series.setData(data);
      const priceLines = [
        ['Range High', levels.range_high, '#60a5fa'],
        ['Range Low', levels.range_low, '#60a5fa'],
        ['Stop', levels.stop, '#ef4444'],
        ['Target', levels.target, '#22c55e'],
      ];
      priceLines.forEach(([title, price, color]) => {{
        if (price !== null && price !== undefined && price !== '-') {{
          series.createPriceLine({{
            price: Number(price),
            color,
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dashed,
            axisLabelVisible: true,
            title,
          }});
        }}
      }});
      if (data.length > 1) {{
        chart.timeScale().fitContent();
      }}

      const watermark = document.createElement('div');
      watermark.textContent = `${{symbol}} ${{label}} - CT`;
      watermark.style.position = 'absolute';
      watermark.style.left = '18px';
      watermark.style.top = '14px';
      watermark.style.color = '#7d8796';
      watermark.style.font = '600 14px Inter, Segoe UI, sans-serif';
      root.appendChild(watermark);
    </script>
    """
