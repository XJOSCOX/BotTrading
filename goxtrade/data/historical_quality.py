"""Strict offline quality reports; calendar coverage never implies provider retention."""
from datetime import datetime, timezone
import math
import pandas as pd

from goxtrade.market.instruments import instrument, validate_contract_instrument


def utc(value):
    stamp = pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise ValueError("Timezone-aware timestamps required")
    return stamp.tz_convert("UTC")


def interval(start, end):
    start, end = utc(start), utc(end)
    if start != start.floor("min") or end != end.floor("min") or not start < end or end-start > pd.Timedelta(days=366):
        raise ValueError("Use aligned minutes, an exclusive end, and a range no longer than 366 days")
    return start, end


def expected_minutes(start, end):
    """Reuse the application's CME Equity calendar, including breaks/holidays/DST."""
    import pandas_market_calendars as calendars
    start, end = interval(start, end)
    schedule = calendars.get_calendar("CME_Equity").schedule((start-pd.Timedelta(days=2)).date(), (end+pd.Timedelta(days=1)).date())
    segments = []
    for _, row in schedule.iterrows():
        opened, closed = utc(row.market_open), utc(row.market_close)
        pieces = [(opened, closed)]
        if pd.notna(row.get("break_start")) and pd.notna(row.get("break_end")):
            pieces = [(opened, utc(row.break_start)), (utc(row.break_end), closed)]
        for a,b in pieces:
            a,b = max(a,start), min(b,end)
            if a < b:
                segments.extend(pd.date_range(a,b,freq="min",inclusive="left"))
    return pd.DatetimeIndex(sorted(set(segments)), tz="UTC") if not segments else pd.DatetimeIndex(sorted(set(segments)))


def quality(frame, metadata, *, now=None, calendar=None):
    start,end = interval(metadata["start"],metadata["end"])
    product = instrument(metadata["symbol"])
    validate_contract_instrument(product.symbol,metadata["contract_id"])
    now = utc(now or datetime.now(timezone.utc))
    errors, warnings, invalid, duplicates, zeros = [], [], 0, 0, 0
    if metadata.get("granularity",1) != 1:
        return dict(status="unsupported", eligible=False, errors=["Only finalized one-minute OHLCV is supported"], candles=len(frame))
    required = {"time","open","high","low","close","volume"}
    if not required <= set(frame):
        errors.append("Required timezone-aware minute OHLCV columns missing")
    valid = []
    times = []
    if not errors:
        for row in frame.to_dict("records"):
            try:
                stamp = utc(row["time"])
                times.append(stamp)
                prices = [row[k] for k in ("open","high","low","close")]
                if stamp != stamp.floor("min") or not start <= stamp < end or stamp+pd.Timedelta(minutes=1) > now:
                    raise ValueError("Nonfinal, out-of-range or misaligned bar")
                if row.get("contract_id", metadata["contract_id"]) != metadata["contract_id"] or row.get("complete",True) is not True:
                    raise ValueError("Mixed contracts or partial bar")
                if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and v > 0 for v in prices):
                    raise ValueError("Invalid prices")
                if row["high"] < max(prices) or row["low"] > min(prices):
                    raise ValueError("Invalid OHLC relationships")
                if any(abs(v/product.tick_size-round(v/product.tick_size)) > 1e-6 for v in prices):
                    raise ValueError("OHLC off tick grid")
                volume = row["volume"]
                if not isinstance(volume,(int,float)) or isinstance(volume,bool) or not math.isfinite(volume) or volume < 0:
                    raise ValueError("Missing, negative or nonfinite volume")
                zeros += volume == 0
                valid.append(stamp)
            except (ValueError,TypeError,OverflowError):
                invalid += 1
        duplicates = len(times)-len(set(times))
        if times != sorted(times):
            errors.append("Out-of-order observations; explicit normalized import required")
        if invalid:
            errors.append(f"{invalid} invalid, nonfinal, missing-volume or mismatched bars")
        if duplicates:
            errors.append(f"{duplicates} duplicate timestamps")
    verified = metadata.get("calendar_reviewed") is True and bool(metadata.get("calendar_note","").strip())
    expected = expected_minutes(start,end) if calendar is None else calendar
    unique = set(valid)
    missing, unexpected = sorted(set(expected)-unique), sorted(unique-set(expected))
    if unexpected:
        warnings.append("Bars outside modeled exchange session; calendar/source review required")
    if not verified:
        warnings.append("Calendar model not operator-reviewed; official coverage percentage withheld")
    if not metadata.get("source") or not metadata.get("volume_provenance") or not metadata.get("expiration"):
        warnings.append("Source, volume provenance and actual contract expiration required")
    if missing:
        warnings.append("Missing expected intervals; no synthetic candles inserted")
    if zeros:
        warnings.append("Zero-volume bars retained and flagged, not fabricated or deleted")
    if end < now-pd.Timedelta(days=2):
        warnings.append("Historical interval ends more than two days ago; not a live-feed freshness failure")
    blocking = not verified or missing or unexpected or not all(metadata.get(k) for k in ("source","volume_provenance","expiration"))
    status = "invalid" if errors else "unavailable" if frame.empty else "partial" if blocking else "complete"
    return dict(status=status,eligible=status=="complete",symbol=product.symbol,contract_id=metadata["contract_id"],
        expiration=metadata.get("expiration"),timezone="UTC",granularity=1,candles=len(frame),earliest=min(valid).isoformat() if valid else None,
        latest=max(valid).isoformat() if valid else None,requested_start=start.isoformat(),requested_end=end.isoformat(),
        expected_candles=len(expected) if verified else None,modeled_expected_candles=len(expected),missing_candles=len(missing),
        duplicate_candles=duplicates,invalid_candles=invalid,zero_volume_candles=int(zeros),unexpected_candles=len(unexpected),
        coverage_percent=100*len(unique & set(expected))/len(expected) if verified and len(expected) else None,
        missing_samples=[s.isoformat() for s in missing[:20]],source=metadata.get("source"),calendar="CME_Equity / operator review required",
        calendar_reviewed=verified,calendar_review_reference=metadata.get("calendar_note"),verified_at=now.isoformat(),errors=errors,warnings=warnings)
