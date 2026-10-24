from __future__ import annotations

import pandas as pd


def candles_from_ticks(data: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if data.empty:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume", "tick_count"])

    frame = data.dropna(subset=["time", "price"]).copy()
    if frame.empty:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume", "tick_count"])

    frame["bucket"] = pd.to_datetime(frame["time"], utc=True).dt.floor(timeframe)
    candles = frame.groupby("bucket", as_index=False).agg(
        open=("price", "first"),
        high=("price", "max"),
        low=("price", "min"),
        close=("price", "last"),
        volume=("volume", "sum"),
        tick_count=("price", "size"),
    )
    return candles.rename(columns={"bucket": "time"})


def minute_candles_from_ticks(data: pd.DataFrame) -> pd.DataFrame:
    return candles_from_ticks(data, "min")


def fifteen_minute_candles_from_ticks(data: pd.DataFrame) -> pd.DataFrame:
    return candles_from_ticks(data, "15min")


def evaluate_crt(candles: pd.DataFrame) -> dict:
    if len(candles) < 3:
        return {
            "signal": "WAIT",
            "reason": "Need at least 3 completed 15-minute candles.",
            "entry": None,
            "stop": None,
            "target": None,
            "range_high": None,
            "range_low": None,
            "last_close": None,
        }

    completed = candles.iloc[:-1]
    if len(completed) < 2:
        return {
            "signal": "WAIT",
            "reason": "Waiting for a completed candle.",
            "entry": None,
            "stop": None,
            "target": None,
            "range_high": None,
            "range_low": None,
            "last_close": None,
        }

    range_candle = completed.iloc[-2]
    signal_candle = completed.iloc[-1]
    current_candle = candles.iloc[-1]

    range_high = float(range_candle["high"])
    range_low = float(range_candle["low"])
    signal_high = float(signal_candle["high"])
    signal_low = float(signal_candle["low"])
    signal_close = float(signal_candle["close"])
    current_close = float(current_candle["close"])

    if signal_low < range_low and signal_close > range_low:
        if current_close <= signal_low:
            return {
                "signal": "WAIT",
                "reason": "CRT long setup was invalidated because live price is already below the sweep low.",
                "entry": None,
                "stop": signal_low,
                "target": range_high,
                "range_high": range_high,
                "range_low": range_low,
                "last_close": current_close,
            }
        return {
            "signal": "LONG",
            "reason": "Previous candle swept the CRT low and closed back inside the range.",
            "entry": current_close,
            "stop": signal_low,
            "target": range_high,
            "range_high": range_high,
            "range_low": range_low,
            "last_close": current_close,
        }

    if signal_high > range_high and signal_close < range_high:
        if current_close >= signal_high:
            return {
                "signal": "WAIT",
                "reason": "CRT short setup was invalidated because live price is already above the sweep high.",
                "entry": None,
                "stop": signal_high,
                "target": range_low,
                "range_high": range_high,
                "range_low": range_low,
                "last_close": current_close,
            }
        return {
            "signal": "SHORT",
            "reason": "Previous candle swept the CRT high and closed back inside the range.",
            "entry": current_close,
            "stop": signal_high,
            "target": range_low,
            "range_high": range_high,
            "range_low": range_low,
            "last_close": current_close,
        }

    return {
        "signal": "WAIT",
        "reason": "No CRT sweep-and-reclaim setup on the last completed candle.",
        "entry": None,
        "stop": None,
        "target": None,
        "range_high": range_high,
        "range_low": range_low,
        "last_close": current_close,
    }
