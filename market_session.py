from datetime import datetime, time
from zoneinfo import ZoneInfo


CENTRAL = ZoneInfo("America/Chicago")


def market_session(now: datetime | None = None) -> dict:
    """Standard futures week; exchange holiday overrides are not included."""
    if now is not None and now.tzinfo is None:
        raise ValueError("Session time must be timezone-aware")
    local = (now or datetime.now(CENTRAL)).astimezone(CENTRAL)
    clock = local.time()
    weekday = local.weekday()
    if weekday == 5 or (weekday == 4 and clock >= time(16)) or (weekday == 6 and clock < time(17)):
        name, opened = "Weekend closed", False
    elif time(16) <= clock < time(17):
        name, opened = "Daily break", False
    elif time(8, 30) <= clock < time(15):
        name, opened = "Regular", True
    elif time(15) <= clock < time(16):
        name, opened = "Extended", True
    else:
        name, opened = "Overnight", True
    return {"name": name, "is_open": opened, "time": local}


def session_signal(signal: dict, session: dict) -> dict:
    if session["is_open"]:
        return signal
    return {**signal, "signal": "PAUSED", "reason": f"{session['name']} - outside scheduled trading hours.",
            "entry": None, "stop": None, "target": None}
