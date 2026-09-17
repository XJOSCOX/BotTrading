"""One-contract watch-signal estimates, not execution or account P&L."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

# CME E-mini contract multipliers in USD per index point.
# https://www.cmegroup.com/content/dam/cmegroup/education/files/understanding-stock-index-futures.pdf
POINT_VALUES = {"NQ=F": Decimal("20"), "ES=F": Decimal("50"), "YM=F": Decimal("5")}


def dollars(row, exit_price):
    multiplier = POINT_VALUES.get(row.get("symbol"))
    if multiplier is None or row.get("entry") is None or exit_price is None or row.get("signal") not in ("LONG", "SHORT"):
        return None
    try:
        entry, exit_value = Decimal(str(row["entry"])), Decimal(str(exit_price))
        if not entry.is_finite() or not exit_value.is_finite():
            return None
        direction = 1 if row["signal"] == "LONG" else -1
        return ((exit_value - entry) * multiplier * direction).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return None


def money(value):
    if value is None:
        return "--"
    return f'{"-" if value < 0 else "+" if value > 0 else ""}${abs(value):,.2f}'


def dollar_summary(rows):
    won, lost, missing = Decimal("0"), Decimal("0"), 0
    for row in rows:
        if row.get("status") != "Closed":
            continue
        value = dollars(row, row.get("exit_price"))
        if value is None:
            missing += 1
        elif value > 0:
            won += value
        else:
            lost += value
    return dict(won=won, lost=lost, net=won + lost, missing=missing)
