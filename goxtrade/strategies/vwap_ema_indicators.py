"""Causal OHLCV indicators, with explicit session coverage and provisional bars."""
from datetime import timedelta
import math
from zoneinfo import ZoneInfo

import pandas as pd

from goxtrade.strategies.signal_candles import signal_candles
from goxtrade.strategies.vwap_ema_config import VwapEmaConfig


OHLCV = ["time", "open", "high", "low", "close", "volume"]


def utc_time(value):
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        raise ValueError("Timezone-aware timestamps are required")
    return stamp.tz_convert("UTC")


def validate_minutes(minutes):
    if not set(OHLCV) <= set(minutes.columns):
        raise ValueError("Actual minute OHLCV data is required")
    frame = minutes.copy()
    if frame.empty:
        frame["time"] = pd.to_datetime(frame["time"], utc=True)
        return frame
    if any(pd.Timestamp(value).tzinfo is None for value in frame["time"]):
        raise ValueError("Minute timestamps must include a timezone")
    frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="raise")
    if frame["time"].duplicated().any() or not frame["time"].eq(frame["time"].dt.floor("min")).all():
        raise ValueError("Minute data must be unique and aligned to minute boundaries")
    for column in OHLCV[1:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    values = frame[OHLCV[1:]]
    if not values.map(lambda value: math.isfinite(value)).all().all():
        raise ValueError("Missing or nonfinite OHLCV data")
    if (frame["volume"] < 0).any() or (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("Invalid prices or negative trade volume")
    if ((frame["high"] < frame[["open", "low", "close"]].max(axis=1)) |
            (frame["low"] > frame[["open", "high", "close"]].min(axis=1))).any():
        raise ValueError("Inconsistent OHLC values")
    return frame.sort_values("time").reset_index(drop=True)


def session_anchor(stamp, config):
    stamp = utc_time(stamp).tz_convert(config.timezone)
    clock = config.anchor_clock
    date = stamp.date()
    try:
        anchor = pd.Timestamp(f"{date} {clock}", tz=config.timezone)
        if stamp < anchor:
            anchor = pd.Timestamp(f"{date - timedelta(days=1)} {clock}", tz=config.timezone)
        end = pd.Timestamp(f"{anchor.date() + timedelta(days=1)} {clock}", tz=config.timezone)
    except Exception as error:
        raise ValueError("Session boundary is ambiguous or nonexistent at this DST transition") from error
    return anchor.tz_convert("UTC"), end.tz_convert("UTC")


def open_minutes(stamps, config=None):
    """Scheduled futures closures only; an unencoded holiday gap suppresses entries."""
    local = pd.DatetimeIndex(stamps).tz_convert("America/Chicago")
    minute = local.hour * 60 + local.minute
    day = local.weekday
    result = (day != 5) & ~((day == 4) & (minute >= 960)) & ~((day == 6) & (minute < 1020))
    result &= ~((minute >= 960) & (minute < 1020))
    if config is not None and config.anchor == "rth":
        anchored = pd.DatetimeIndex(stamps).tz_convert(config.timezone)
        wall = anchored.hour * 60 + anchored.minute
        result &= (anchored.weekday < 5) & (wall >= 510) & (wall < 900)
    return result


def price_source(frame, source):
    if source == "ohlc4":
        return frame[["open", "high", "low", "close"]].mean(axis=1)
    if source == "hlc3":
        return frame[["high", "low", "close"]].mean(axis=1)
    return frame[source]


def indicator_frame(minutes, now, config=None, sequence=None):
    config = VwapEmaConfig.from_dict(config)
    now = utc_time(now)
    source = validate_minutes(minutes.loc[pd.to_datetime(minutes["time"], utc=True) <= now.floor("min")])
    if "complete" in source:
        source = source.loc[source["complete"].eq(True) | source["time"].eq(now.floor("min"))]
    bars = signal_candles(source, now, config.signal_minutes, strict=True)
    bars["provisional"] = False
    interval = pd.Timedelta(minutes=config.signal_minutes)
    bucket = now.floor(f"{config.signal_minutes}min")
    if config.entry_mode != "CONFIRMED":
        partial = source.loc[source["time"] >= bucket]
        expected = pd.date_range(bucket, now.floor("min"), freq="min")
        if (not partial.empty and len(partial) == len(expected)
                and pd.DatetimeIndex(partial["time"]).equals(expected)
                and sequence is not None and "last_sequence" in partial
                and int(partial.iloc[-1]["last_sequence"]) <= int(sequence)
                and int(partial.iloc[-1]["last_sequence"]) > 0
                and "asof_time" in partial
                and pd.to_datetime(partial["asof_time"], utc=True).le(now).all()):
            row = dict(time=bucket, open=partial.iloc[0]["open"], high=partial["high"].max(),
                       low=partial["low"].min(), close=partial.iloc[-1]["close"],
                       volume=partial["volume"].sum(), provisional=True)
            bars = pd.concat([bars, pd.DataFrame([row])], ignore_index=True)
    if bars.empty:
        return bars
    bars["closed_at"] = bars["time"] + interval
    bars["session_id"] = [session_anchor(stamp, config)[0].isoformat() for stamp in bars["time"]]
    bars["coverage"] = False
    bars["vwap"] = float("nan")
    known = pd.DatetimeIndex(source["time"])
    for identity, group in bars.groupby("session_id", sort=False):
        anchor = pd.Timestamp(identity)
        end = min(group.iloc[-1]["closed_at"], now.floor("min") + pd.Timedelta(minutes=1))
        expected = pd.date_range(anchor, end, inclusive="left", freq="min")
        expected = expected[open_minutes(expected, config)]
        missing = expected.difference(known)
        first_gap = missing.min() if len(missing) else end
        covered = group["closed_at"].le(first_gap) | (group["provisional"] & (first_gap >= now.floor("min") + pd.Timedelta(minutes=1)))
        covered &= group["time"].ge(anchor)
        covered &= open_minutes(pd.DatetimeIndex(group["time"]), config)
        eligible = pd.Series(open_minutes(pd.DatetimeIndex(group["time"]), config), index=group.index)
        volume = group["volume"].where(eligible, 0).cumsum()
        vwap = (price_source(group, config.vwap_source) * group["volume"].where(eligible, 0)).cumsum() / volume.replace(0, float("nan"))
        bars.loc[group.index, "coverage"] = covered
        bars.loc[group.index, "vwap"] = vwap.where(covered)
    # EMA carries across scheduled closures, but restarts after missing open-market bars.
    segment = []
    current = 0
    previous = None
    for stamp in bars["time"]:
        if previous is not None and stamp != previous + interval:
            between = pd.date_range(previous + interval, stamp, inclusive="left", freq="min")
            if open_minutes(between, config).any():
                current += 1
        segment.append(current)
        previous = stamp
    bars["segment"] = segment
    bars["ema"] = float("nan")
    bars["atr"] = float("nan")
    bars["warmup"] = 0
    for _, group in bars.groupby("segment", sort=False):
        prices = price_source(group, config.ema_source)
        bars.loc[group.index, "ema"] = prices.ewm(span=config.ema_length, adjust=False, min_periods=config.ema_length).mean()
        previous_close = group["close"].shift()
        ranges = pd.concat([group["high"] - group["low"], (group["high"] - previous_close).abs(),
                            (group["low"] - previous_close).abs()], axis=1).max(axis=1)
        bars.loc[group.index, "atr"] = ranges.rolling(config.atr_length, min_periods=config.atr_length).mean()
        bars.loc[group.index, "warmup"] = range(1, len(group) + 1)
    bars["gap"] = bars["ema"] - bars["vwap"]
    return bars
