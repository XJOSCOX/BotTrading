import math

TICK_SIZES = {"NQ=F": .25, "ES=F": .25, "YM=F": 1.0, "MNQ=F": .25, "MES=F": .25}


def valid_price(symbol, value):
    if value is None:
        return None
    try:
        value = float(value)
        if not math.isfinite(value):
            return None
        step = TICK_SIZES.get(symbol)
        if step is None:
            return value
        units = value / step
        return round(units) * step if abs(units - round(units)) < 1e-7 else None
    except (TypeError, ValueError):
        return None


def price_predicate(symbol):
    step = TICK_SIZES.get(symbol)
    return "price IS NOT NULL" if step is None else f"price IS NOT NULL AND ABS(price / {step} - ROUND(price / {step})) < 0.0000001"
