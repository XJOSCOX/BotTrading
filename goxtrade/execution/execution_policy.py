"""Research policy is stored separately; it cannot arm or resize a broker account."""
from dataclasses import asdict, dataclass, fields

from goxtrade.execution.trade_candidate import finite, frozen_json
from goxtrade.strategies.strategy_catalog import SPECS, strategy_spec


@dataclass(frozen=True)
class ExecutionPolicy:
    version: str = "manager-shadow-v1"
    mode: str = "conservative"
    monitoring: tuple = tuple(s.id for s in SPECS)
    participating: tuple = tuple(s.id for s in SPECS)
    priority: tuple = tuple(s.id for s in SPECS)
    symbols: tuple = ("MNQ", "MES")
    max_trade_risk: float = 75.
    max_open_risk: float = 150.
    max_daily_loss: float = 500.
    max_daily_loss_with_open: float = 500.
    max_positions: int = 1
    max_per_symbol: int = 1
    max_contracts: int = 4
    requested_quantity: int = 1
    max_group_positions: int = 1
    max_group_risk: float = 150.
    max_group_gross: float = 200000.
    max_group_net: float = 200000.
    max_daily_trades: int = 20
    max_consecutive_losses: int = 3
    cooldown_minutes: int = 5
    minimum_rr: float = 0.
    commission_per_side: float | None = None
    zero_cost_acknowledged: bool = False
    slippage_ticks: int = 1
    protective_buffer: float = 0.
    strategy_budgets: tuple = ()
    paper_enabled: bool = False

    def validate(self):
        if self.version != "manager-shadow-v1" or self.mode not in ("conservative", "first_confirmed", "configured_priority", "evidence_research"):
            raise ValueError("Unsupported manager policy")
        for name in ("monitoring", "participating", "priority"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or len(values) != len(set(values)):
                raise ValueError("Strategy lists must contain unique registered identities")
            for value in values:
                if strategy_spec(value).id != value:
                    raise ValueError("Use canonical strategy IDs")
        if not set(self.participating) <= set(self.monitoring) or not set(self.participating) <= set(self.priority):
            raise ValueError("Participating strategies require monitoring and explicit priority")
        if not self.symbols or len(set(self.symbols)) != len(self.symbols) or not set(self.symbols) <= {"MNQ", "MES", "MYM", "NQ", "ES", "YM"}:
            raise ValueError("Select supported research instruments")
        for name in ("max_trade_risk", "max_open_risk", "max_daily_loss", "max_daily_loss_with_open", "max_group_risk", "max_group_gross", "max_group_net"):
            if not finite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.max_daily_loss > 500 or self.max_daily_loss_with_open > 500:
            raise ValueError("Research loss limits cannot exceed the existing $500 protection")
        for name in ("max_positions", "max_per_symbol", "max_contracts", "requested_quantity", "max_group_positions", "max_daily_trades", "max_consecutive_losses"):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= 100:
                raise ValueError(f"{name} must be a bounded positive integer")
        if not 1 <= self.requested_quantity <= self.max_contracts <= 4 or self.max_per_symbol != 1:
            raise ValueError("Maximum four contracts; pyramiding is not supported")
        for name, upper in (("cooldown_minutes", 1440), ("slippage_ticks", 100)):
            if type(getattr(self, name)) is not int or not 0 <= getattr(self, name) <= upper:
                raise ValueError(f"Invalid {name}")
        if not finite(self.minimum_rr) or not 0 <= self.minimum_rr <= 100 or not finite(self.protective_buffer) or not 0 <= self.protective_buffer <= 10000:
            raise ValueError("Invalid risk buffer or minimum RR")
        if type(self.paper_enabled) is not bool or type(self.zero_cost_acknowledged) is not bool:
            raise ValueError("Policy switches must be booleans")
        if self.commission_per_side is not None and (not finite(self.commission_per_side) or not 0 <= self.commission_per_side <= 100):
            raise ValueError("Enter finite nonnegative commissions")
        if self.commission_per_side == 0 and not self.zero_cost_acknowledged:
            raise ValueError("Zero fees require explicit sensitivity acknowledgement")
        if self.paper_enabled and self.commission_per_side is None:
            raise ValueError("Paper mode requires explicit costs")
        seen = set()
        for strategy, amount in self.strategy_budgets:
            strategy_spec(strategy)
            if strategy in seen or not finite(amount) or amount <= 0:
                raise ValueError("Invalid per-strategy research budget")
            seen.add(strategy)
        frozen_json(asdict(self))
        return self

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, values):
        if not isinstance(values, dict) or set(values)-{f.name for f in fields(cls)}:
            raise ValueError("Unknown manager policy fields")
        copied = dict(values)
        for name in ("monitoring", "participating", "priority", "symbols", "strategy_budgets"):
            if name in copied:
                if not isinstance(copied[name], (tuple, list)):
                    raise ValueError("Policy lists must be arrays")
                copied[name] = tuple(tuple(v) if isinstance(v, list) else v for v in copied[name])
        return cls(**copied).validate()
