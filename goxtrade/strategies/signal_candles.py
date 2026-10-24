"""Complete, gap-checked signal candles built from persisted minute history."""
import pandas as pd


def signal_candles(minutes, now, interval=15, strict=False):
    if type(interval) is not int or not 1 <= interval <= 60:
        raise ValueError("Candle interval must be 1-60 minutes")
    frame = minutes.copy()
    frame["time"] = pd.to_datetime(frame["time"],utc=True)
    if strict and frame["time"].duplicated().any():
        raise ValueError("Duplicate source minutes")
    frame = frame.loc[frame["time"]+pd.Timedelta(minutes=1)<=pd.Timestamp(now)].sort_values("time").drop_duplicates("time",keep="last")
    rows = []
    for stamp, group in frame.groupby(frame["time"].dt.floor(f"{interval}min")):
        expected = pd.date_range(stamp,periods=interval,freq="min")
        if len(group)!=interval or not group["time"].reset_index(drop=True).equals(pd.Series(expected)):
            continue
        rows.append(dict(time=stamp,open=group.iloc[0]["open"],high=group["high"].max(),low=group["low"].min(),
                         close=group.iloc[-1]["close"],volume=group["volume"].sum(min_count=interval)))
    return pd.DataFrame(rows,columns=["time","open","high","low","close","volume"])
