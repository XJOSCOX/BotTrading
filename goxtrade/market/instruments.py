"""Outright futures specifications, sourced from CME (see strategy documentation)."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR


@dataclass(frozen=True)
class Instrument:
    symbol: str
    tick_size: float
    point_value: float

    @property
    def tick_value(self):
        return self.tick_size * self.point_value


INSTRUMENTS = {s: Instrument(s, tick, value) for s, tick, value in (
    ("NQ", .25, 20.), ("MNQ", .25, 2.), ("ES", .25, 50.),
    ("MES", .25, 5.), ("YM", 1., 5.), ("MYM", 1., .5),
)}


def instrument(symbol):
    try:
        return INSTRUMENTS[symbol.removesuffix("=F")]
    except (KeyError, AttributeError) as error:
        raise ValueError("Unsupported futures instrument") from error


def round_tick(price, tick, up=False):
    units = Decimal(str(price)) / Decimal(str(tick))
    return float(units.to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR) * Decimal(str(tick)))
