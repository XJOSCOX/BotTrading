from __future__ import annotations

import pandas as pd


RSI_PERIOD = 14
OVERSOLD = 30.0
OVERBOUGHT = 70.0
EXTREME_MINUTES = 5


def add_rsi(candles: pd.DataFrame, period: int = RSI_PERIOD) -> pd.DataFrame:
    if candles.empty:
        return candles.assign(rsi=pd.Series(dtype="float64"))

    frame = candles.copy()
    delta = frame["close"].diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = losses.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    frame["rsi"] = 100 - (100 / (1 + rs))
    frame.loc[(avg_loss == 0) & (avg_gain > 0), "rsi"] = 100.0
    frame.loc[(avg_gain == 0) & (avg_loss > 0), "rsi"] = 0.0
    return frame


def consecutive_extreme_count(values: pd.Series, side: str) -> int:
    count = 0
    for value in reversed(values.dropna().tolist()):
        if side == "low" and value <= OVERSOLD:
            count += 1
        elif side == "high" and value >= OVERBOUGHT:
            count += 1
        else:
            break
    return count


def evaluate_reversal(candles: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    candles_with_rsi = add_rsi(candles)
    completed = candles_with_rsi.iloc[:-1]
    current = candles_with_rsi.iloc[-1] if not candles_with_rsi.empty else None

    if len(completed) < RSI_PERIOD + 2 or current is None:
        return (
            {
                "signal": "WAIT",
                "reason": "Need more completed 1-minute candles for RSI reversal.",
                "entry": None,
                "stop": None,
                "target": None,
                "range_high": None,
                "range_low": None,
                "last_close": None if current is None else float(current["close"]),
                "rsi": None,
                "extreme_minutes": 0,
            },
            candles_with_rsi,
        )

    previous = completed.iloc[-1]
    prior = completed.iloc[-2]
    previous_rsi = previous["rsi"]
    prior_rsi = prior["rsi"]
    current_close = float(current["close"])
    rsi = None if pd.isna(previous_rsi) else float(previous_rsi)
    low_extreme_count = consecutive_extreme_count(completed["rsi"], "low")
    high_extreme_count = consecutive_extreme_count(completed["rsi"], "high")

    if pd.notna(prior_rsi) and pd.notna(previous_rsi):
        if prior_rsi <= OVERSOLD and previous_rsi > OVERSOLD:
            return (
                {
                    "signal": "LONG",
                    "reason": "RSI reclaimed 30 after touching the oversold zone.",
                    "entry": current_close,
                    "stop": float(previous["low"]),
                    "target": float(previous["high"]),
                    "range_high": float(previous["high"]),
                    "range_low": float(previous["low"]),
                    "last_close": current_close,
                    "rsi": rsi,
                    "extreme_minutes": low_extreme_count,
                },
                candles_with_rsi,
            )

        if previous_rsi <= OVERSOLD and low_extreme_count < EXTREME_MINUTES:
            return (
                {
                    "signal": "LONG WATCH",
                    "reason": f"RSI is touching or below 30 for {low_extreme_count} completed minute(s).",
                    "entry": current_close,
                    "stop": float(previous["low"]),
                    "target": float(previous["high"]),
                    "range_high": float(previous["high"]),
                    "range_low": float(previous["low"]),
                    "last_close": current_close,
                    "rsi": rsi,
                    "extreme_minutes": low_extreme_count,
                },
                candles_with_rsi,
            )

        if prior_rsi >= OVERBOUGHT and previous_rsi < OVERBOUGHT:
            return (
                {
                    "signal": "SHORT",
                    "reason": "RSI rejected 70 after touching the overbought zone.",
                    "entry": current_close,
                    "stop": float(previous["high"]),
                    "target": float(previous["low"]),
                    "range_high": float(previous["high"]),
                    "range_low": float(previous["low"]),
                    "last_close": current_close,
                    "rsi": rsi,
                    "extreme_minutes": high_extreme_count,
                },
                candles_with_rsi,
            )

        if previous_rsi >= OVERBOUGHT and high_extreme_count < EXTREME_MINUTES:
            return (
                {
                    "signal": "SHORT WATCH",
                    "reason": f"RSI is touching or above 70 for {high_extreme_count} completed minute(s).",
                    "entry": current_close,
                    "stop": float(previous["high"]),
                    "target": float(previous["low"]),
                    "range_high": float(previous["high"]),
                    "range_low": float(previous["low"]),
                    "last_close": current_close,
                    "rsi": rsi,
                    "extreme_minutes": high_extreme_count,
                },
                candles_with_rsi,
            )

    if low_extreme_count >= EXTREME_MINUTES:
        return (
            {
                "signal": "LONG WATCH",
                "reason": f"RSI has stayed at or below 30 for {low_extreme_count} completed minutes.",
                "entry": current_close,
                "stop": float(completed.tail(EXTREME_MINUTES)["low"].min()),
                "target": float(completed.tail(EXTREME_MINUTES)["high"].max()),
                "range_high": float(completed.tail(EXTREME_MINUTES)["high"].max()),
                "range_low": float(completed.tail(EXTREME_MINUTES)["low"].min()),
                "last_close": current_close,
                "rsi": rsi,
                "extreme_minutes": low_extreme_count,
            },
            candles_with_rsi,
        )

    if high_extreme_count >= EXTREME_MINUTES:
        return (
            {
                "signal": "SHORT WATCH",
                "reason": f"RSI has stayed at or above 70 for {high_extreme_count} completed minutes.",
                "entry": current_close,
                "stop": float(completed.tail(EXTREME_MINUTES)["high"].max()),
                "target": float(completed.tail(EXTREME_MINUTES)["low"].min()),
                "range_high": float(completed.tail(EXTREME_MINUTES)["high"].max()),
                "range_low": float(completed.tail(EXTREME_MINUTES)["low"].min()),
                "last_close": current_close,
                "rsi": rsi,
                "extreme_minutes": high_extreme_count,
            },
            candles_with_rsi,
        )

    return (
        {
            "signal": "WAIT",
            "reason": "RSI has not reclaimed 30, rejected 70, or stayed extreme for 5 minutes.",
            "entry": None,
            "stop": None,
            "target": None,
            "range_high": float(previous["high"]),
            "range_low": float(previous["low"]),
            "last_close": current_close,
            "rsi": rsi,
            "extreme_minutes": max(low_extreme_count, high_extreme_count),
        },
        candles_with_rsi,
    )
