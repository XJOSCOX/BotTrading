"""Validated, serializable parameters; no broker or persistence dependencies."""
from dataclasses import asdict, dataclass, fields
from datetime import datetime
import hashlib
import json
import math
from zoneinfo import ZoneInfo


MODES = ("CONFIRMED", "REALTIME", "ANTICIPATORY")
SOURCES = ("close", "open", "high", "low", "hlc3", "ohlc4")


@dataclass(frozen=True)
class VwapEmaConfig:
    monitor_enabled: bool = True
    practice_enabled: bool = False
    leader_enabled: bool = False
    paper_enabled: bool = False
    paper_quantity: int = 1
    paper_commission_per_side: float = 0.
    paper_zero_cost_sensitivity: bool = False
    paper_max_initial_risk_usd: float = 0.
    paper_min_effective_rr: float = 0.
    paper_slippage_ticks: float = 1.
    entry_mode: str = "CONFIRMED"
    signal_minutes: int = 3
    ema_length: int = 9
    ema_source: str = "close"
    vwap_source: str = "ohlc4"
    anchor: str = "futures"
    custom_anchor: str = "17:00"
    timezone: str = "America/Chicago"
    enabled_symbols: tuple = ("NQ=F", "ES=F", "YM=F")
    warmup_bars: int = 45
    entry_window_seconds: int = 90
    max_data_age_seconds: int = 10
    cooldown_minutes: int = 0
    separation_enabled: bool = False
    separation_ticks: float = 1.0
    separation_atr: float = 0.0
    ema_slope_enabled: bool = False
    vwap_slope_enabled: bool = False
    volume_enabled: bool = False
    volume_lookback: int = 20
    volume_multiplier: float = 1.0
    volatility_enabled: bool = False
    atr_min_ticks: float = 0.0
    atr_max_ticks: float = 1000.0
    session_filter_enabled: bool = False
    sessions: tuple = ("Regular", "Extended", "Overnight")
    custom_windows: tuple = ("08:30-15:00",)
    distance_enabled: bool = False
    max_distance_ticks: float = 8.0
    max_distance_atr: float = 0.0
    anticipation_distance_ticks: float = 4.0
    anticipation_observations: int = 3
    anticipation_min_slope_ticks: float = 0.0
    stop_method: str = "buffered"
    atr_length: int = 14
    atr_multiple: float = 1.5
    swing_bars: int = 3
    fixed_stop_ticks: int = 12
    reward_risk: float = 2.0
    management_method: str = "adaptive"
    management_minutes: int = 5
    trail_start_r: float = 1.5
    trail_ticks: int = 12
    breakeven_r: float = 1.0
    notify_signals: bool = True
    notify_wait: bool = False

    @property
    def anchor_clock(self):
        return {"futures": "17:00", "rth": "08:30"}.get(self.anchor, self.custom_anchor)

    def to_dict(self):
        return asdict(self)

    @property
    def fingerprint(self):
        values = self.to_dict()
        if not values.pop("leader_enabled"):
            return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:16]
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()[:16]

    @classmethod
    def from_dict(cls, values=None):
        if isinstance(values, cls):
            return values.validate()
        values = dict(values or {})
        unknown = values.keys() - {field.name for field in fields(cls)}
        if unknown:
            raise ValueError("Unknown strategy settings: " + ", ".join(sorted(unknown)))
        for name in ("enabled_symbols", "sessions", "custom_windows"):
            if name in values:
                if not isinstance(values[name], (list, tuple)):
                    raise ValueError(f"{name} must be a list")
                values[name] = tuple(values[name])
        return cls(**values).validate()

    def validate(self):
        defaults = VwapEmaConfig()
        for field in fields(self):
            value, default = getattr(self, field.name), getattr(defaults, field.name)
            if type(default) is bool and type(value) is not bool:
                raise ValueError(f"{field.name} must be true or false")
            if type(default) is int and (type(value) is not int or value < 0):
                raise ValueError(f"{field.name} must be a nonnegative integer")
            if type(default) is float and (type(value) not in (float, int) or not math.isfinite(value) or value < 0):
                raise ValueError(f"{field.name} must be finite and nonnegative")
        if self.entry_mode not in MODES or self.signal_minutes not in (1, 3, 5, 10, 15, 30, 60):
            raise ValueError("Unsupported entry mode or signal timeframe")
        if self.ema_source not in SOURCES or self.vwap_source not in SOURCES:
            raise ValueError("Unsupported indicator price source")
        if not 2 <= self.ema_length <= 200 or not max(self.ema_length, 15) <= self.warmup_bars <= 2000:
            raise ValueError("EMA length or warmup is outside its supported range")
        if self.anchor not in ("futures", "rth", "custom"):
            raise ValueError("Unknown session anchor")
        try:
            zone = ZoneInfo(self.timezone)
            clock = datetime.strptime(self.anchor_clock, "%H:%M")
            for month in (1, 7):
                offset = datetime(2026, month, 15, clock.hour, clock.minute, tzinfo=zone).utcoffset().total_seconds() / 60
                if (clock.hour * 60 + clock.minute - offset) % self.signal_minutes:
                    raise ValueError("Session boundary must align with UTC candle buckets")
        except (KeyError, TypeError) as error:
            raise ValueError("Use a valid IANA session timezone") from error
        if not self.enabled_symbols or not set(self.enabled_symbols) <= {"NQ=F", "ES=F", "YM=F", "MNQ=F", "MES=F", "MYM=F"}:
            raise ValueError("Choose supported futures symbols")
        if not set(self.sessions) <= {"Regular", "Extended", "Overnight", "First hour", "Custom"}:
            raise ValueError("Unsupported trading session filter")
        for window in self.custom_windows:
            try:
                begin, end = window.split("-")
                datetime.strptime(begin, "%H:%M")
                datetime.strptime(end, "%H:%M")
            except (ValueError, AttributeError) as error:
                raise ValueError("Custom windows use HH:MM-HH:MM") from error
        if not 1 <= self.entry_window_seconds <= 600 or not 1 <= self.max_data_age_seconds <= 30 or self.cooldown_minutes > 1440:
            raise ValueError("Entry timing settings are outside their supported range")
        if not 2 <= self.volume_lookback <= 200 or not 2 <= self.atr_length <= 200:
            raise ValueError("Indicator lookbacks must be 2-200")
        if self.atr_max_ticks <= self.atr_min_ticks or self.anticipation_observations < 2:
            raise ValueError("Invalid volatility bounds or convergence observation count")
        if self.stop_method not in ("atr", "swing", "fixed", "buffered") or self.management_method not in ("fixed", "trailing", "breakeven", "adaptive"):
            raise ValueError("Unsupported stop or management method")
        if self.management_minutes not in (1, 3, 5, 10, 15, 30) or not 1 <= self.swing_bars <= 50:
            raise ValueError("Unsupported management timeframe or swing lookback")
        if not 1 <= self.fixed_stop_ticks <= 10000 or not 1 <= self.trail_ticks <= 10000:
            raise ValueError("Tick distances must be 1-10000")
        if not 1 <= self.paper_quantity <= 4:
            raise ValueError("Paper quantity must be 1-4")
        if not 0 < self.reward_risk <= 20 or not 0 < self.atr_multiple <= 20 or self.trail_start_r <= 0 or self.breakeven_r <= 0:
            raise ValueError("Risk ratios must be positive and within bounds")
        return self
