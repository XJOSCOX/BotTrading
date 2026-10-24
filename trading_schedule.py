"""Conservative Topstep execution window, separate from the market-data session."""
from datetime import datetime, time
from market_session import CENTRAL


def execution_schedule(now=None):
    now = now or datetime.now(CENTRAL)
    if now.tzinfo is None:
        raise ValueError("Timezone-aware time required")
    local = now.astimezone(CENTRAL)
    clock, day = local.time(), local.weekday()
    weekend = day == 5 or (day == 4 and clock >= time(15,5)) or (day == 6 and clock < time(17))
    flatten = weekend or time(15,5) <= clock < time(17)
    blocked = flatten or time(14,50) <= clock < time(17)
    reason = ("Scheduled flat window: close bot positions from 15:05 CT; no entries until the next 17:00 CT session"
              if flatten else "Late-session entry cutoff: no new orders after 14:50 CT" if blocked else "Execution session open")
    return dict(allow_entry=not blocked, flatten=flatten, reason=reason)
