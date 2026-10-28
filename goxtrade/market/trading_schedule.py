"""Conservative Topstep execution window, separate from the market-data session."""
from datetime import datetime, time
from goxtrade.market.market_session import CENTRAL


def execution_schedule(now=None, *, calendar=True):
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
    result = dict(allow_entry=not blocked, flatten=flatten, reason=reason)
    if calendar:
        from goxtrade.market.calendar_guard import restriction
        overlay = restriction(now)
        if not overlay["allow_entry"]:
            result.update(allow_entry=False, flatten=flatten or overlay["flatten"], reason=overlay["reason"])
        if result['allow_entry']:
            from goxtrade.market.economic_calendar import entry_block
            news = entry_block(now)
            if news:
                result.update(allow_entry=False, reason=news)
    return result
