"""Pure all-candidate evaluation. No I/O, broker imports, arming or submissions."""
from dataclasses import replace
import json

from goxtrade.execution.execution_decisions import ExecutionDecision
from goxtrade.execution.execution_policy import ExecutionPolicy
from goxtrade.execution.portfolio_risk import Exposure, authorize_risk
from goxtrade.execution.signal_arbitration import arbitrate
from goxtrade.execution.trade_candidate import digest, finite, frozen_json, stamp
from goxtrade.market.instruments import instrument, validate_contract_instrument
from goxtrade.strategies.strategy_catalog import strategy_spec


def eligibility(candidate, state, policy, now, scope):
    try:
        spec = strategy_spec(candidate.strategy_id)
        if spec.name != candidate.strategy_name:
            return "REJECTED", "Strategy ID and display name disagree"
        if candidate.strategy_id not in policy.monitoring or candidate.strategy_id not in policy.participating:
            return "EXECUTION_DISABLED", "Strategy does not participate in research arbitration"
        if candidate.account_id != state.account_id or candidate.profile != state.profile:
            return "REJECTED", "Exact account/profile mismatch"
        if not state.account_id or state.profile not in ("research", "paper", "practice", "leader"):
            return "REJECTED", "Account identity is incomplete"
        if candidate.symbol not in policy.symbols:
            return "EXECUTION_DISABLED", "Instrument is not authorized by this research policy"
        if dict(state.contracts).get(candidate.symbol) != candidate.contract_id:
            return "REJECTED", "Active actual contract mismatch or rollover"
        validate_contract_instrument(candidate.symbol, candidate.contract_id)
        if not candidate.contract_id or not candidate.setup_id or not candidate.candidate_id:
            return "REJECTED", "Missing contract, candidate or source setup identity"
        expected_id = digest(dict(strategy=candidate.strategy_id, setup=candidate.setup_id, account=candidate.account_id,
                                  profile=candidate.profile, contract=candidate.contract_id, direction=candidate.direction))
        if expected_id != candidate.candidate_id:
            return "REJECTED", "Candidate identity does not match its immutable envelope"
        if candidate.direction not in ("LONG", "SHORT") or candidate.classification not in spec.modes:
            return "REJECTED", "Unsupported direction or signal classification"
        config = json.loads(candidate.config_json)
        for content in (config, json.loads(candidate.evidence_json), json.loads(candidate.risk_json)):
            frozen_json(content)
        if not isinstance(config, dict):
            return "REJECTED", "Frozen configuration must be an object"
        if type(candidate.timeframe) is not int or candidate.timeframe <= 0:
            return "REJECTED", "Invalid signal timeframe"
        if candidate.timeframe != (config.get("signal_minutes", spec.signal_minutes) if spec.id == "vwap_ema_cross" else spec.signal_minutes):
            return "REJECTED", "Signal interval disagrees with frozen strategy configuration"
        if candidate.management_mode not in ("fixed", "structure-v1", "trailing", "breakeven"):
            return "REJECTED", "Frozen exit-management mode is not supported"
        management = json.loads(candidate.risk_json)
        if not isinstance(management, dict):
            return "REJECTED", "Frozen risk metadata must be an object"
        if candidate.management_mode == "structure-v1" and management.get("management_minutes") not in (1, 3, 5, 10, 15, 30, 60):
            return "REJECTED", "Adaptive exit interval is missing from frozen ownership metadata"
        if candidate.management_mode == "trailing" and (not finite(management.get("trail_ticks")) or management["trail_ticks"] <= 0):
            return "REJECTED", "Trailing distance is missing from frozen ownership metadata"
        if not isinstance(candidate.session, str) or candidate.session in ("", "unspecified"):
            return "REJECTED", "Source trading session identity is missing"
        created, confirmed, expiry, current = map(stamp, (candidate.created_at, candidate.confirmed_at, candidate.expires_at, now))
        if created > current or confirmed > current or expiry <= confirmed or created >= expiry:
            return "REJECTED", "Unobservable or inconsistent signal timestamps"
        if current >= expiry:
            return "EXPIRED", "Signal entry window expired"
        max_window = 600 if spec.runtime_adapter is None else config.get("entry_window_seconds", spec.expiration_seconds)
        if not finite(max_window) or not 0 < max_window <= 600 or (expiry-confirmed).total_seconds() > max_window:
            return "REJECTED", "Entry expiration exceeds the registered/frozen policy window"
        if not candidate.quote_at or not 0 <= (current-stamp(candidate.quote_at)).total_seconds() <= 10:
            return "DATA_UNAVAILABLE", "Executable price is stale or unavailable"
        if not 0 <= (current-stamp(state.observed_at)).total_seconds() <= 10:
            return "DATA_UNAVAILABLE", "Portfolio state snapshot is stale"
        if candidate.history_complete is not True:
            return "DATA_UNAVAILABLE", "Required candle history is not verified complete"
        if candidate.confirmed is not True:
            return "REJECTED", "Strategy entry confirmation has not been revalidated"
        if candidate.execution_eligible is not True:
            return "EXECUTION_DISABLED", "Strategy execution eligibility is not established"
        levels = (candidate.entry_reference, candidate.price, candidate.stop, candidate.target)
        if not all(finite(v) and v > 0 for v in levels):
            return "REJECTED", "Missing or invalid entry, structural stop or target"
        tick = instrument(candidate.symbol).tick_size
        if any(abs(v/tick-round(v/tick)) > 1e-6 for v in levels):
            return "REJECTED", "Entry levels do not match instrument tick grid"
        rr = candidate.reward_risk
        if rr is None:
            return "REJECTED", "Executable price invalidates stop/target geometry"
        if rr < policy.minimum_rr:
            return "RISK_BLOCKED", "Reward/risk below configured minimum"
        if candidate.setup_id in state.consumed:
            return "REJECTED", "Source setup already consumed"
        if (type(state.daily_trades) is not int or state.daily_trades < 0 or type(state.consecutive_losses) is not int or state.consecutive_losses < 0
                or not isinstance(state.positions, tuple) or not isinstance(state.reservations, tuple)
                or len(dict(state.contracts)) != len(state.contracts)):
            return "REJECTED", "Incomplete or ambiguous account risk state"
        if any(type(getattr(state, key)) is not bool for key in (
                "session_allowed", "paused", "armed", "reconciled", "unresolved", "emergency", "loss_locked")):
            return "REJECTED", "Account safety switches must be verified booleans"
        if state.emergency or state.paused:
            return "EXECUTION_DISABLED", "Emergency stop or account pause is active"
        if state.unresolved:
            return "RISK_BLOCKED", "Unresolved order, reservation or unowned exposure"
        if not state.session_allowed:
            return "EXECUTION_DISABLED", state.session_reason
        if scope == "broker":
            return "EXECUTION_DISABLED", "Manager broker cutover is prohibited in this milestone"
        if scope == "shadow" and (not state.reconciled or not state.armed):
            return "EXECUTION_DISABLED", "Broker reconciliation/arming is not freshly verified; shadow only"
        return "ELIGIBLE", "Historical eligibility verified; broker preflight not performed"
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return "REJECTED", "Malformed or ambiguous candidate/state metadata"


def evaluate(candidates, state, policy=None, now=None, *, scope="historical"):
    policy = (policy or ExecutionPolicy()).validate()
    if scope not in ("historical", "paper", "shadow", "broker"):
        raise ValueError("Unknown manager evaluation scope")
    current = stamp(now).isoformat()
    candidates = tuple(candidates)
    group = digest(dict(account=state.account_id, profile=state.profile, time=current,
                        candidates=sorted(c.candidate_id for c in candidates), policy=policy.to_dict()))
    decisions, eligible, counts = {}, [], {}
    for candidate in candidates:
        counts[candidate.candidate_id] = counts.get(candidate.candidate_id, 0)+1
    for candidate in candidates:
        status, reason = eligibility(candidate, state, policy, current, scope)
        if counts[candidate.candidate_id] > 1:
            status, reason = "REJECTED", "Duplicate candidate identity in decision batch"
        if status == "ELIGIBLE" and policy.mode == "evidence_research":
            status, reason = "EXECUTION_DISABLED", "Evidence ranking unavailable: reviewed out-of-sample ranking artifact required"
        decision = ExecutionDecision(candidate.candidate_id, candidate.strategy_id, candidate.profile, group, current,
                                     status, (reason,), policy_version=policy.version, mode=policy.mode,
                                     checks_scope="broker_not_authorized" if scope == "broker" else "shadow_not_preflight" if scope == "shadow" else "historical_only")
        decisions[candidate.candidate_id] = decision
        if status == "ELIGIBLE":
            eligible.append(candidate)
    winners, blocked, supports = arbitrate(eligible, policy)
    for candidate_id, conflicts in blocked.items():
        opposite = any(c.candidate_id in conflicts and c.direction != next(v.direction for v in eligible if v.candidate_id == candidate_id) for c in eligible)
        decisions[candidate_id] = replace(decisions[candidate_id], eligibility="CONFLICTED", conflicts=conflicts,
                                         reasons=("NO TRADE - conflicting directions" if opposite else "Same-direction support; one position owner selected",),
                                         selected_candidate_id=None if opposite else conflicts[0])
    working = state
    for candidate in winners:
        risk = authorize_risk(candidate, working, policy, current)
        if not risk["allowed"]:
            decisions[candidate.candidate_id] = replace(decisions[candidate.candidate_id], eligibility="RISK_BLOCKED",
                                                       reasons=(risk["reason"],), available_budget=risk["available_budget"])
            continue
        decisions[candidate.candidate_id] = replace(decisions[candidate.candidate_id], selected=True,
            selected_candidate_id=candidate.candidate_id, support=supports[candidate.candidate_id],
            planned_risk=risk["planned_risk"], available_budget=risk["available_budget"], quantity=risk["quantity"],
            reasons=(risk["reason"],), execution_status="WOULD_SELECT" if scope == "shadow" else "SIMULATION_SELECTED")
        exposure = Exposure(candidate.symbol, candidate.contract_id, candidate.direction, risk["quantity"],
                            candidate.price, candidate.stop, candidate.strategy_id, candidate.candidate_id, protected=True, status="reserved")
        working = replace(working, reservations=(*working.reservations, exposure))
    return tuple(decisions[key] for key in sorted(decisions))
