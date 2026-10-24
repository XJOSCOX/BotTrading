"""Chart payloads share the indicator engine, not a second indicator formula."""
import pandas as pd

from goxtrade.ui.market.live_chart_component import _chart


def chart_payload(frame, config, events=(), signal=None):
    points, markers = [], []
    previous = None
    for row in frame.to_dict("records"):
        epoch = int(pd.Timestamp(row["time"]).timestamp())
        point = {key: float(row[key]) for key in ("open", "high", "low", "close", "volume")}
        point.update(time=epoch, strategy_ema=None if pd.isna(row["ema"]) else float(row["ema"]),
                     strategy_vwap=None if pd.isna(row["vwap"]) else float(row["vwap"]))
        points.append(point)
        valid = (not row["provisional"] and row["coverage"] and row["warmup"] >= config.warmup_bars)
        if valid and previous and previous["coverage"] and previous["session_id"] == row["session_id"]:
            direction = "LONG" if previous["gap"] <= 0 < row["gap"] else "SHORT" if previous["gap"] >= 0 > row["gap"] else None
            if direction:
                markers.append(marker(epoch, direction, "Confirmed cross", "#65d6bc" if direction == "LONG" else "#f28c98"))
        previous = row
    times = {point["time"] for point in points}
    for event in events:
        epoch = int(pd.Timestamp(event["candle_time"]).timestamp())
        if event.get("entry_mode") != "CONFIRMED" and epoch in times:
            markers.append(marker(epoch, event["direction"], event.get("raw_signal", event["entry_mode"]), "#edbf68"))
    levels = {key: signal.get(key) for key in ("entry", "stop", "target")} if signal else {}
    return dict(points=points, markers=sorted(markers, key=lambda row: row["time"]), levels=levels)


def marker(epoch, direction, text, color):
    return dict(time=epoch, position="belowBar" if direction == "LONG" else "aboveBar", color=color,
                shape="arrowUp" if direction == "LONG" else "arrowDown", text=text)


def render_strategy_chart(frame, symbol, config, events=(), signal=None, height=650):
    _chart(**chart_payload(frame, config, events, signal), symbol=symbol, height=height,
           range_label="All", timeframe=f"{config.signal_minutes}min", candle_label=f"{config.signal_minutes} min",
           strategy_overlay=True, ema_label=f"EMA {config.ema_length}",
           metrics=[("Mode", config.entry_mode, "Provisional modes can repaint", ""),
                    ("Signal", (signal or {}).get("raw_signal", (signal or {}).get("signal", "WAIT")), "", "")],
           key=f"vwap_chart_{symbol}_{config.signal_minutes}", default=None)
