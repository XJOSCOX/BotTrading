"""Validated research parameters. Saving never arms a broker account."""
from dataclasses import asdict, dataclass, fields
from datetime import datetime
import hashlib
import json
import math


@dataclass(frozen=True)
class PreviousDayBoxConfig:
    monitor_enabled: bool = True
    practice_enabled: bool = False
    leader_enabled: bool = False
    paper_enabled: bool = False
    session: str = "futures"
    custom_open: str = "17:00"
    custom_close: str = "16:00"
    buy_percent: float = 25.
    sell_percent: float = 75.
    confirmation: str = "wick"
    combined_logic: str = "OR"
    outside_mode: str = "reclaim"
    wick_body_enabled: bool = False
    wick_body_ratio: float = 2.
    wick_range_enabled: bool = False
    wick_range_ratio: float = .5
    directional_close: bool = False
    close_midpoint: bool = False
    close_location: float = .5
    min_candle_ticks: int = 1
    min_sweep_ticks: int = 1
    sweep_boundary: str = "extreme"
    next_candle_confirmation: bool = False
    swing_lookback: int = 3
    entry_window_seconds: int = 90
    max_data_age_seconds: int = 10
    max_zone_extension_percent: float = 5.
    max_entry_drift_ticks: int = 8
    stop_method: str = "rejection"
    stop_buffer_ticks: int = 2
    fixed_stop_ticks: int = 12
    atr_length: int = 14
    atr_multiple: float = 1.5
    target_method: str = "midpoint"
    reward_risk: float = 2.
    management_minutes: int = 5
    trail_start_r: float = 1.5
    cooldown_minutes: int = 0
    max_entries_per_box: int = 0
    atr_filter_enabled: bool = False
    atr_min_ticks: float = 0.
    atr_max_ticks: float = 1000.
    volume_enabled: bool = False
    volume_lookback: int = 20
    volume_multiplier: float = 1.
    ema_enabled: bool = False
    ema_length: int = 20
    vwap_enabled: bool = False
    min_box_enabled: bool = False
    min_box_ticks: int = 20
    max_box_enabled: bool = False
    max_box_ticks: int = 1000
    previous_direction_enabled: bool = False
    time_filter_enabled: bool = False
    entry_open: str = "08:30"
    entry_close: str = "14:50"
    minimum_effective_rr: float = 0.
    estimated_commission_per_side: float = 0.
    zero_cost_sensitivity: bool = False
    paper_quantity: int = 1
    paper_commission_per_side: float = 0.
    paper_zero_cost_sensitivity: bool = False
    paper_slippage_ticks: float = 1.
    paper_max_initial_risk_usd: float = 0.
    paper_min_effective_rr: float = 0.
    enabled_symbols: tuple = ("NQ=F", "ES=F", "YM=F")
    notify_signals: bool = True
    notify_wait: bool = False

    @property
    def signal_minutes(self):
        return 15

    @property
    def entry_mode(self):
        return "CONFIRMED"

    def to_dict(self):
        return asdict(self)

    @property
    def fingerprint(self):
        values = self.to_dict()
        if not values.pop("leader_enabled"):
            return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:16]
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()[:16]

    @classmethod
    def from_dict(cls, value=None):
        if isinstance(value, cls):
            return value.validate()
        value = dict(value or {})
        if value.keys()-{field.name for field in fields(cls)}:
            raise ValueError("Unknown previous-day box settings")
        if "enabled_symbols" in value:
            if not isinstance(value["enabled_symbols"], (list, tuple)):
                raise ValueError("enabled_symbols must be a list")
            value["enabled_symbols"] = tuple(value["enabled_symbols"])
        return cls(**value).validate()

    def validate(self):
        default = PreviousDayBoxConfig()
        for field in fields(self):
            value, initial = getattr(self, field.name), getattr(default, field.name)
            if type(initial) is bool and type(value) is not bool:
                raise ValueError(field.name+" must be true or false")
            if type(initial) is int and (type(value) is not int or not 0 <= value <= 10000):
                raise ValueError(field.name+" must be a bounded nonnegative integer")
            if type(initial) is float and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                raise ValueError(field.name+" must be finite and nonnegative")
            if type(initial) is str and type(value) is not str:
                raise ValueError(field.name+" must be text")
        choices = dict(session=("futures","rth","custom"),confirmation=("wick","sweep","structure","combined"),
                       combined_logic=("AND","OR"),outside_mode=("ignore","reclaim","breakout_research"),
                       sweep_boundary=("extreme","zone"),stop_method=("rejection","box","swing","atr","fixed","buffered"),
                       target_method=("midpoint","opposite_zone","opposite_boundary","rr","adaptive"))
        if any(getattr(self, name) not in allowed for name,allowed in choices.items()):
            raise ValueError("Unsupported box session, confirmation or risk method")
        if not 0 < self.buy_percent < 50 < self.sell_percent < 100:
            raise ValueError("Buy/sell zones must not overlap and must surround the midpoint")
        if not 0 < self.close_location <= 1 or not 0 <= self.wick_range_ratio <= 1:
            raise ValueError("Candle proportions must be within 0-1")
        if not (1 <= self.entry_window_seconds <= 600 and 1 <= self.max_data_age_seconds <= 60
                and 1 <= self.paper_quantity <= 4 and self.paper_slippage_ticks % 1 == 0
                and self.fixed_stop_ticks > 0 and 0 < self.reward_risk <= 100 and 0 < self.atr_multiple <= 100
                and 2 <= self.atr_length <= 200 and 1 <= self.swing_lookback <= 20
                and 2 <= self.ema_length <= 200 and 2 <= self.volume_lookback <= 200
                and self.management_minutes in (5,10,15) and self.max_zone_extension_percent < 25):
            raise ValueError("Box timeframe, entry window, risk or lookback is outside supported limits")
        if self.atr_min_ticks > self.atr_max_ticks:
            raise ValueError("ATR minimum exceeds maximum")
        for name in ("custom_open","custom_close","entry_open","entry_close"):
            if datetime.strptime(getattr(self,name), "%H:%M").strftime("%H:%M") != getattr(self,name):
                raise ValueError(name+" must use HH:MM format")
        if self.custom_open == self.custom_close or self.entry_open == self.entry_close:
            raise ValueError("Session and entry windows must have distinct boundaries")
        if not self.enabled_symbols or not set(self.enabled_symbols) <= {s+"=F" for s in ("NQ","MNQ","ES","MES","YM","MYM")}:
            raise ValueError("Choose supported futures symbols")
        if self.paper_enabled and self.paper_commission_per_side == 0 and not self.paper_zero_cost_sensitivity:
            raise ValueError("Paper commission must be explicit or acknowledged zero-cost sensitivity")
        if self.minimum_effective_rr and not self.estimated_commission_per_side and not self.zero_cost_sensitivity:
            raise ValueError("Effective RR filter requires an explicit fee estimate or acknowledged zero-cost sensitivity")
        return self
