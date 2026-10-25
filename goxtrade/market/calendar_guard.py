"""Optional, operator-reviewed CME windows can only restrict the existing schedule."""
import json
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import pandas as pd
from goxtrade.paths import DATA_DIR

CALENDAR_PATH = DATA_DIR / "execution_calendar.json"


def stamp(value):
    result = pd.Timestamp(value)
    if pd.isna(result) or result.tzinfo is None:
        raise ValueError("Calendar timestamps must include timezone offsets")
    return result.tz_convert("UTC")


def validate(values, now):
    if not isinstance(values, dict) or type(values.get("schema_version")) is not int or values.get("schema_version") != 1:
        raise ValueError("Unsupported reviewed calendar schema")
    ZoneInfo(values["timezone"])
    source = urlparse(values["source_url"])
    if source.scheme != "https" or source.hostname not in ("www.cmegroup.com", "cmegroup.com"):
        raise ValueError("Calendar must reference the reviewed official CME source")
    if values.get("product_group") != "US equity index futures":
        raise ValueError("Reviewed calendar must cover the supported US equity index futures")
    reviewed, begin, end = (stamp(values[key]) for key in ("reviewed_at", "valid_from", "valid_until"))
    now = stamp(now)
    if not reviewed <= now < end or not begin <= now or end <= begin:
        raise ValueError("Calendar is expired, future-dated or outside its coverage")
    if now-reviewed > pd.Timedelta(days=7) or end-reviewed > pd.Timedelta(days=7):
        raise ValueError("Calendar review is stale; review at least weekly")
    intervals = []
    if not isinstance(values.get("sessions"), list):
        raise ValueError("Calendar sessions must be a list of verified open/close pairs")
    for row in values["sessions"]:
        opened, closed = stamp(row["open"]), stamp(row["close"])
        if not begin <= opened < closed <= end:
            raise ValueError("Calendar session lies outside declared coverage")
        intervals.append((opened, closed))
    intervals.sort()
    if any(right[0] < left[1] for left, right in zip(intervals, intervals[1:])):
        raise ValueError("Calendar sessions overlap")
    return intervals


def restriction(now, required=False):
    if not CALENDAR_PATH.exists():
        return dict(allow_entry=not required, flatten=False,
                    reason="Reviewed CME calendar is not configured; VWAP broker Practice is blocked")
    try:
        values = json.loads(CALENDAR_PATH.read_text(encoding="utf-8"))
        intervals = validate(values, now)
    except (OSError, ValueError, KeyError, TypeError) as error:
        return dict(allow_entry=False, flatten=False, reason=f"Reviewed CME calendar unavailable: {error}")
    now = stamp(now)
    current = next(((begin, end) for begin, end in intervals if begin <= now < end), None)
    if current is None:
        return dict(allow_entry=False, flatten=True, reason="Reviewed CME calendar: exchange closed")
    remaining = current[1]-now
    return dict(allow_entry=remaining > pd.Timedelta(minutes=15), flatten=remaining <= pd.Timedelta(minutes=5),
                reason="Reviewed CME calendar: close buffer" if remaining <= pd.Timedelta(minutes=15) else "Reviewed CME calendar window open")


def entry_block(now):
    state = restriction(now, required=True)
    return None if state["allow_entry"] else state["reason"]
