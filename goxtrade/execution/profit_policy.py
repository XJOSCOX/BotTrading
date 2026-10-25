"""Frozen post-entry research policies. Nothing here grants broker permission."""
from dataclasses import asdict, dataclass, fields
from goxtrade.execution.trade_candidate import finite, frozen_json


@dataclass(frozen=True)
class ProfitPolicy:
    version: str = "profit-v1"
    enabled: bool = False
    mode: str = "baseline"
    target_method: str = "strategy"
    target_r: float = 2.
    target_ticks: int = 20
    target_points: float = 10.
    final_target_enabled: bool = False
    break_even_enabled: bool = False
    break_even_r: float = 1.
    break_even_buffer_ticks: int = 0
    break_even_cover_costs: bool = False
    trailing_method: str = "fixed_ticks"
    trail_start_r: float = 1.5
    trail_ticks: int = 20
    atr_multiple: float = 2.
    management_minutes: int = 5
    structure_lookback: int = 3
    profit_lock_enabled: bool = False
    profit_lock_r: float = 1.5
    retain_fraction: float = .5
    partial_targets: tuple = ()  # (R milestone, whole-contract quantity)
    max_data_age_seconds: int = 10

    def validate(self):
        if self.version != "profit-v1" or self.mode not in ("baseline", "fixed", "breakeven", "trailing", "profit_lock", "partial", "hybrid"):
            raise ValueError("Unknown profit policy")
        if self.target_method not in ("strategy", "structural", "rr", "ticks", "points") or self.trailing_method not in ("fixed_ticks", "atr", "structure", "extreme", "adaptive"):
            raise ValueError("Unknown target or trailing method")
        for key in ("enabled", "final_target_enabled", "break_even_enabled", "break_even_cover_costs", "profit_lock_enabled"):
            if type(getattr(self, key)) is not bool:
                raise ValueError("Profit-policy switches must be booleans")
        for key in ("target_r", "target_points", "break_even_r", "trail_start_r", "atr_multiple", "profit_lock_r"):
            if not finite(getattr(self, key)) or not 0 < getattr(self, key) <= 10000:
                raise ValueError(f"Invalid {key}")
        for key in ("target_ticks", "trail_ticks", "break_even_buffer_ticks", "structure_lookback", "max_data_age_seconds"):
            value = getattr(self, key)
            if type(value) is not int or not (0 if key == "break_even_buffer_ticks" else 1) <= value <= 10000:
                raise ValueError(f"Invalid {key}")
        if self.management_minutes not in (5, 10, 15) or type(self.management_minutes) is not int or not finite(self.retain_fraction) or not 0 < self.retain_fraction < 1:
            raise ValueError("Use 5/10/15-minute management and a retained fraction strictly between zero and one")
        if not isinstance(self.partial_targets, tuple):
            raise ValueError("Partial targets must be immutable")
        previous = 0.
        for milestone, quantity in self.partial_targets:
            if not finite(milestone) or not previous < milestone <= 100 or type(quantity) is not int or not 1 <= quantity <= 4:
                raise ValueError("Partial milestones must increase and use whole quantities 1-4")
            previous = milestone
        if self.mode == "partial" and not self.partial_targets:
            raise ValueError("Partial mode requires an explicit milestone ladder")
        frozen_json(asdict(self))
        return self

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value)-{field.name for field in fields(cls)}:
            raise ValueError("Unknown profit-policy fields")
        value = dict(value)
        if "partial_targets" in value:
            if not isinstance(value["partial_targets"], (list, tuple)):
                raise ValueError("Partial targets must be an array")
            value["partial_targets"] = tuple(tuple(row) for row in value["partial_targets"])
        return cls(**value).validate()


def comparison_policies():
    """Prespecified experiments, never optimized using future test outcomes."""
    from dataclasses import replace
    base = ProfitPolicy(enabled=True)
    return {"baseline": base,
            **{f"fixed_{r}R": replace(base, mode="fixed", target_method="rr", target_r=r) for r in (1., 1.5, 2.)},
            "breakeven_1R": replace(base, mode="breakeven"),
            "atr_trailing": replace(base, mode="trailing", trailing_method="atr"),
            "structure_trailing": replace(base, mode="trailing", trailing_method="structure"),
            "profit_lock": replace(base, mode="profit_lock"),
            "partial_then_trail": replace(base, mode="partial", partial_targets=((1., 1),)),
            "hybrid": replace(base, mode="hybrid", break_even_enabled=True, profit_lock_enabled=True, partial_targets=((1., 1),))}
