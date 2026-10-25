"""Planned stop exposure, never a promise of maximum loss or an implied hedge."""
from dataclasses import asdict, dataclass
from datetime import timedelta

from goxtrade.execution.trade_candidate import exposure_key, finite, stamp
from goxtrade.market.instruments import instrument
from goxtrade.strategies.strategy_catalog import strategy_spec


@dataclass(frozen=True)
class Exposure:
    symbol: str
    contract_id: str
    direction: str
    quantity: int
    entry: float
    stop: float
    strategy_id: str
    owner: str
    protected: bool = True
    status: str = "open"

    @property
    def risk(self):
        # A stop locked in profit consumes zero price risk, never negative capacity.
        sign = 1 if self.direction == "LONG" else -1
        return max(0., (self.entry-self.stop)*sign)*instrument(self.symbol).point_value*self.quantity

    @property
    def notional(self):
        return abs(self.entry)*instrument(self.symbol).point_value*self.quantity

    @property
    def group(self):
        return strategy_spec(self.strategy_id).correlation_group

    def valid(self):
        return (self.direction in ("LONG", "SHORT") and type(self.quantity) is int and self.quantity > 0
                and all(finite(v) and v > 0 for v in (self.entry, self.stop)) and bool(self.owner)
                and self.protected is True and self.status in ("open", "reserved"))


@dataclass(frozen=True)
class PortfolioState:
    account_id: str
    profile: str
    observed_at: str
    positions: tuple = ()
    reservations: tuple = ()
    realized: float = 0.
    unrealized: float = 0.
    daily_trades: int = 0
    consecutive_losses: int = 0
    last_closed_at: str | None = None
    loss_locked: bool = False
    emergency: bool = False
    paused: bool = False
    reconciled: bool = False
    armed: bool = False
    unresolved: bool = False
    session_allowed: bool = False
    session_reason: str = "Session eligibility unavailable"
    consumed: tuple = ()
    contracts: tuple = ()  # Explicit (instrument, active actual contract) pairs.

    def to_dict(self):
        return asdict(self)


def planned_risk(candidate, quantity, policy):
    product = instrument(candidate.symbol)
    price_risk = abs(candidate.price-candidate.stop)*product.point_value
    return quantity*(price_risk+2*policy.slippage_ticks*product.tick_value+2*policy.commission_per_side)+policy.protective_buffer


def authorize_risk(candidate, state, policy, now):
    exposures = (*state.positions, *state.reservations)
    def blocked(reason, available=0.):
        return dict(allowed=False, reason=reason, quantity=0, planned_risk=None, available_budget=max(0., available))
    if not all(finite(v) for v in (state.realized, state.unrealized)):
        return blocked("Portfolio P&L is unavailable")
    if state.loss_locked or state.realized <= -min(500., policy.max_daily_loss):
        return blocked("Account realized-loss lock")
    if state.realized+min(0., state.unrealized) <= -min(500., policy.max_daily_loss_with_open):
        return blocked("Daily loss including unrealized exposure")
    if state.daily_trades+len(state.reservations) >= policy.max_daily_trades or state.consecutive_losses >= policy.max_consecutive_losses:
        return blocked("Daily trade or consecutive-loss limit")
    if state.last_closed_at and stamp(now) < stamp(state.last_closed_at)+timedelta(minutes=policy.cooldown_minutes):
        return blocked("Post-close entry cooldown")
    try:
        if any(not p.valid() for p in exposures):
            return blocked("Unowned, unprotected or incomplete portfolio exposure")
        if any(exposure_key(p.symbol) == candidate.exposure for p in exposures):
            return blocked("Instrument already open or reserved; ownership is retained")
        if any(p.direction != candidate.direction for p in exposures):
            return blocked("Opposing index exposure; no automatic hedge or reversal")
        if len(exposures) >= policy.max_positions:
            return blocked("Maximum simultaneous positions")
        group = strategy_spec(candidate.strategy_id).correlation_group
        grouped = [p for p in exposures if p.group == group]
        if len(grouped) >= policy.max_group_positions:
            return blocked("Correlated exposure-group position limit")
        if policy.commission_per_side is None:
            return blocked("Explicit commission assumptions required")
        product = instrument(candidate.symbol)
        net_reward = abs(candidate.target-candidate.price)*product.point_value-2*policy.commission_per_side-2*policy.slippage_ticks*product.tick_value
        if policy.minimum_rr and net_reward/planned_risk(candidate, 1, policy) < policy.minimum_rr:
            return blocked("Net reward/risk after costs below configured minimum")
        used = sum(p.risk+p.quantity*(2*policy.commission_per_side+2*policy.slippage_ticks*instrument(p.symbol).tick_value)+policy.protective_buffer for p in exposures)
        group_used = sum(p.risk+p.quantity*(2*policy.commission_per_side+2*policy.slippage_ticks*instrument(p.symbol).tick_value)+policy.protective_buffer for p in grouped)
        strategy_used = sum(p.risk+p.quantity*(2*policy.commission_per_side+2*policy.slippage_ticks*instrument(p.symbol).tick_value)+policy.protective_buffer for p in exposures if p.strategy_id == candidate.strategy_id)
    except (ValueError, TypeError, AttributeError):
        return blocked("Portfolio exposure metadata is invalid")
    available = min(policy.max_trade_risk, policy.max_open_risk-used, policy.max_group_risk-group_used,
                    policy.max_daily_loss+min(0., state.realized), policy.max_daily_loss_with_open+state.realized+min(0., state.unrealized),
                    dict(policy.strategy_budgets).get(candidate.strategy_id, policy.max_open_risk)-strategy_used)
    for quantity in range(min(policy.requested_quantity, policy.max_contracts), 0, -1):
        risk = planned_risk(candidate, quantity, policy)
        gross = sum(p.notional for p in grouped)+abs(candidate.price)*instrument(candidate.symbol).point_value*quantity
        signed = sum(p.notional*(1 if p.direction == "LONG" else -1) for p in grouped)
        net = abs(signed+abs(candidate.price)*instrument(candidate.symbol).point_value*quantity*(1 if candidate.direction == "LONG" else -1))
        if risk <= available and gross <= policy.max_group_gross and net <= policy.max_group_net:
            return dict(allowed=True, reason="Planned stop exposure authorized; gaps/slippage can exceed estimates",
                        quantity=quantity, planned_risk=risk, available_budget=max(0., available))
    return blocked("Minimum contract cannot fit risk or correlated gross/net exposure limits; structural stop retained", available)
