"""Validate user-supplied historical data; never manufacture market observations."""
import hashlib
import io
import math

import pandas as pd

from goxtrade.strategies.vwap_ema_indicators import validate_minutes


class UnsupportedDataset(ValueError):
    pass


def csv_minutes(contents):
    frame = pd.read_csv(io.BytesIO(contents) if isinstance(contents, bytes) else contents)
    return validate_minutes(frame)


def validate_dataset(minutes, contract_id, rollover_policy="single_contract"):
    if not isinstance(contract_id, str) or not contract_id.strip():
        raise ValueError("Select the actual historical contract")
    if rollover_policy != "single_contract":
        raise UnsupportedDataset("Only single-contract datasets are supported; select separate runs around a rollover")
    frame = validate_minutes(minutes)
    if (minutes.attrs.get("contract_id", contract_id) != contract_id
            or "contract_id" in frame and (frame["contract_id"].isna().any() or set(frame["contract_id"].unique()) != {contract_id})):
        raise UnsupportedDataset("Mixed or mismatched contracts cannot be treated as one continuous price series")
    if frame.empty:
        raise ValueError("No historical OHLCV data in the selected range")
    if "complete" in frame and not frame["complete"].eq(True).all():
        raise UnsupportedDataset("Research requires finalized minute bars; partial or unverified capture is present")
    frame.attrs.update(minutes.attrs)
    frame.attrs["contract_id"] = contract_id
    return frame


def dataset_hash(frame):
    columns = [column for column in ("time", "open", "high", "low", "close", "volume", "contract_id") if column in frame]
    return hashlib.sha256(frame[columns].to_csv(index=False, float_format="%.12g").encode()).hexdigest()


def intrabar_snapshot(minutes,partials,row,signal_minutes):
    """Shared actual-trade aggregation for single backtests and portfolio replay."""
    now=pd.Timestamp(row["time"])
    minute=now.floor("min")
    price=float(row["price"])
    part=partials.setdefault(minute,dict(time=minute,open=price,high=price,low=price,close=price,volume=0.))
    part.update(high=max(part["high"],price),low=min(part["low"],price),close=price,
                volume=part["volume"]+float(row["volume"]),last_sequence=int(row["sequence"]),asof_time=now.isoformat())
    known=minutes.loc[minutes["time"]+pd.Timedelta(minutes=1)<=now]
    bucket=now.floor(f"{signal_minutes}min")
    snapshot=pd.concat([known.loc[known["time"]<bucket],pd.DataFrame([value for stamp,value in partials.items() if stamp>=bucket])],ignore_index=True)
    snapshot.attrs.update(minutes.attrs)
    return snapshot


def validate_ticks(ticks, contract_id):
    required = {"time", "sequence", "price", "volume"}
    if ticks is None or not required <= set(ticks.columns):
        raise UnsupportedDataset("This entry mode requires ordered intrabar trades with time, sequence, price, and volume")
    frame = ticks.copy()
    if "event_type" in frame and not frame["event_type"].eq("trade").all():
        raise UnsupportedDataset("Intrabar replay accepts trade observations, not quote updates")
    if frame.empty or any(pd.Timestamp(value).tzinfo is None for value in frame["time"]):
        raise UnsupportedDataset("Timezone-aware trade observations are required")
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    for column in ("sequence", "price", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if (frame[list(required)].isna().any().any() or frame["sequence"].duplicated().any()
            or not frame[["sequence", "price", "volume"]].map(math.isfinite).all().all()
            or (frame["sequence"] <= 0).any() or (frame["sequence"] % 1 != 0).any()
            or not frame["sequence"].is_monotonic_increasing or not frame["time"].is_monotonic_increasing
            or (frame["price"] <= 0).any() or (frame["volume"] < 0).any()):
        raise UnsupportedDataset("Trade observations must be valid, unique, and chronologically sequenced")
    if "contract_id" in frame and set(frame["contract_id"].unique()) != {contract_id}:
        raise UnsupportedDataset("Intrabar trades do not match the selected contract")
    if ticks.attrs.get("contract_id", contract_id) != contract_id:
        raise UnsupportedDataset("Intrabar provenance does not match the selected contract")
    if "event_id" in frame and (frame["event_id"].isna().any() or frame["event_id"].duplicated().any()):
        raise UnsupportedDataset("Duplicate or missing provider trade identities")
    return frame.reset_index(drop=True)
