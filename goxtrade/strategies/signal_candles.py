"""Complete, gap-checked signal candles built from persisted minute history."""
import pandas as pd


def signal_candles(minutes, now, interval=15, strict=False):
    if type(interval) is not int or not 1 <= interval <= 60:
        raise ValueError("Candle interval must be 1-60 minutes")
    frame = minutes.copy()
    frame["time"] = pd.to_datetime(frame["time"],utc=True)
    if strict and frame["time"].duplicated().any():
        raise ValueError("Duplicate source minutes")
    if "complete" in frame:
        frame = frame.loc[frame["complete"].eq(True)]
    if "asof_time" in frame:
        observed = pd.to_datetime(frame["asof_time"], utc=True, errors="coerce")
        frame = frame.loc[frame["asof_time"].isna() | (observed.notna() & observed.le(pd.Timestamp(now)))]
    frame = frame.loc[frame["time"]+pd.Timedelta(minutes=1)<=pd.Timestamp(now)].sort_values("time").drop_duplicates("time",keep="last")
    columns = ["time", "open", "high", "low", "close", "volume"]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    frame = frame.assign(_bucket=frame["time"].dt.floor(f"{interval}min"),
                         _aligned=frame["time"].eq(frame["time"].dt.floor("min")))
    groups = frame.groupby("_bucket", sort=True)
    counts = groups.size()
    first = groups.head(1).set_index("_bucket")
    last = groups.tail(1).set_index("_bucket")
    # Unique, aligned minutes with the exact count and endpoints cannot hide gaps.
    valid = (counts.eq(interval) & groups["_aligned"].all()
             & first["time"].eq(counts.index)
             & last["time"].eq(counts.index + pd.Timedelta(minutes=interval-1)))
    index = counts.index[valid]
    if index.empty:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(dict(time=index, open=first.loc[index,"open"].to_numpy(),
                            high=groups["high"].max().loc[index].to_numpy(),
                            low=groups["low"].min().loc[index].to_numpy(),
                            close=last.loc[index,"close"].to_numpy(),
                            volume=groups["volume"].sum(min_count=interval).loc[index].to_numpy()),
                        columns=columns)
