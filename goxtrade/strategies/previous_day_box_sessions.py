"""Exchange-calendar sessions and strict, contract-specific prior-session coverage."""
from datetime import timedelta
from functools import lru_cache
import hashlib
import json

import pandas as pd


@lru_cache(maxsize=128)
def _schedule(day):
    import pandas_market_calendars as calendars
    stamp = pd.Timestamp(day)
    return calendars.get_calendar("CME_Equity").schedule((stamp-pd.Timedelta(days=16)).date(), (stamp+pd.Timedelta(days=2)).date())


def session_windows(now, config, schedule=None):
    now = pd.Timestamp(now).tz_convert("UTC")
    source = _schedule(str(now.tz_convert("America/Chicago").date())) if schedule is None else schedule
    windows = []
    for label, row in source.iterrows():
        opened, closed = (pd.Timestamp(row[name]).tz_convert("UTC") for name in ("market_open","market_close"))
        if config.session != "futures":
            date = pd.Timestamp(label).date()
            start_clock, end_clock = ("08:30","15:00") if config.session == "rth" else (config.custom_open,config.custom_close)
            begin = date-timedelta(days=int(start_clock > end_clock))
            start = pd.Timestamp(f"{begin} {start_clock}",tz="America/Chicago").tz_convert("UTC")
            end = pd.Timestamp(f"{date} {end_clock}",tz="America/Chicago").tz_convert("UTC")
            opened, closed = max(opened,start), min(closed,end)
        if opened >= closed:
            continue
        segments = [(opened,closed)]
        if pd.notna(row.get("break_start")) and pd.notna(row.get("break_end")):
            bs,be = (pd.Timestamp(row[name]).tz_convert("UTC") for name in ("break_start","break_end"))
            if opened < bs < be < closed:
                segments = [(opened,bs),(be,closed)]
        windows.append(dict(id=str(pd.Timestamp(label).date()),open=opened,close=closed,segments=segments))
    return windows


def previous_box(minutes, now, config, contract_id, schedule=None):
    windows = session_windows(now,config,schedule)
    now = pd.Timestamp(now).tz_convert("UTC")
    current = next((row for row in windows if row["open"] <= now < row["close"]), None)
    cutoff = current["open"] if current else now
    eligible = [row for row in windows if row["close"] <= cutoff]
    if not eligible:
        raise ValueError("No completed eligible previous session in exchange calendar")
    previous = eligible[-1]
    expected = pd.DatetimeIndex([stamp for start,end in previous["segments"] for stamp in pd.date_range(start,end,freq="min",inclusive="left")])
    if minutes.empty or minutes.attrs.get("contract_id") != contract_id:
        raise ValueError("Previous-session history contract is missing or mismatched")
    frame = minutes.copy()
    frame["time"] = pd.to_datetime(frame["time"],utc=True,errors="raise")
    frame = frame.loc[frame["time"].isin(expected)]
    if (frame["time"].duplicated().any() or len(frame) != len(expected)
            or not frame["time"].sort_values().reset_index(drop=True).equals(pd.Series(expected))):
        raise ValueError("Previous trading session minute history is incomplete; no older box substituted")
    if "complete" in frame and not frame["complete"].eq(True).all():
        raise ValueError("Previous trading session includes incomplete capture")
    if "asof_time" in frame and (pd.to_datetime(frame["asof_time"],utc=True) > now).any():
        raise ValueError("Previous trading session was not yet available at evaluation time")
    prices = frame[["open","high","low","close"]]
    import numpy as np
    if (not np.isfinite(prices.to_numpy()).all() or (prices <= 0).any().any()
            or (frame["high"] < frame[["open","close","low"]].max(axis=1)).any()
            or (frame["low"] > frame[["open","close","high"]].min(axis=1)).any()):
        raise ValueError("Invalid prior-session OHLC")
    high,low = float(frame["high"].max()),float(frame["low"].min())
    if high <= low:
        raise ValueError("Previous session has no positive price range")
    result = dict(session_id=previous["id"],session_definition=config.session,timezone="America/Chicago",
                  opened_at=previous["open"].isoformat(),closed_at=previous["close"].isoformat(),contract_id=contract_id,
                  pdh=high,pdl=low,midpoint=(high+low)/2,range=high-low,
                  buy_upper=low+(high-low)*config.buy_percent/100,sell_lower=low+(high-low)*config.sell_percent/100,
                  session_direction="LONG" if frame.iloc[-1]["close"]>frame.iloc[0]["open"] else "SHORT")
    result["version"] = hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()[:16]
    return result


def zone(price, box):
    if price < box["pdl"]: return "Below PDL"
    if price > box["pdh"]: return "Above PDH"
    if price <= box["buy_upper"]: return "Discount"
    if price >= box["sell_lower"]: return "Premium"
    return "Neutral"
