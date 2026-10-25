"""Shared causal portfolio kernel, isolated from strategy paper and broker history."""
from dataclasses import replace
from datetime import timedelta
import copy
import math
import json
from zoneinfo import ZoneInfo

from goxtrade.execution.execution_policy import ExecutionPolicy
from goxtrade.execution.portfolio_risk import Exposure, PortfolioState, planned_risk
from goxtrade.execution.strategy_manager import evaluate
from goxtrade.execution.trade_candidate import TradeCandidate, finite, stamp
from goxtrade.market.instruments import instrument
from goxtrade.research.metrics import statistics, breakdown
from goxtrade.strategies.adaptive_exit import MODE


def empty_portfolio(account="portfolio-paper", profile="paper"):
    if profile not in ("paper", "research"):
        raise ValueError("Portfolio simulation cannot target broker profiles")
    return dict(account=account, profile=profile, cursor=0, last_observed_at=None, positions=[], pending=[],
                consumed=[], trades=[], decisions=[], candidates=[], marks={}, realized=0., daily_realized=0.,
                daily_trades=0, consecutive_losses=0, last_closed_at=None, day=None, equity=[0.],
                data_rejections=[], policy_version="manager-shadow-v1")


def trading_day(now):
    # CME trading date rolls at the evening reopen, not at local midnight.
    return (stamp(now).astimezone(ZoneInfo("America/Chicago"))+timedelta(hours=7)).date().isoformat()


def state_at(state, policy, now, *, session_allowed, session_reason, contracts):
    positions = tuple(Exposure(**position["exposure"]) for position in state["positions"])
    reservations = tuple(Exposure(**position["exposure"]) for position in state["pending"])
    unrealized, missing = 0., False
    for position in positions:
        mark = state["marks"].get(position.symbol)
        if not mark or mark["contract_id"] != position.contract_id or not 0 <= (stamp(now)-stamp(mark["time"])).total_seconds() <= 10:
            missing = True
            continue
        unrealized += (mark["price"]-position.entry)*(1 if position.direction == "LONG" else -1)*instrument(position.symbol).point_value*position.quantity
    return PortfolioState(state["account"], state["profile"], stamp(now).isoformat(), positions=positions,
                          reservations=reservations, realized=state["daily_realized"], unrealized=unrealized,
                          daily_trades=state["daily_trades"], consecutive_losses=state["consecutive_losses"],
                          last_closed_at=state["last_closed_at"], unresolved=missing,
                          session_allowed=session_allowed, session_reason=session_reason,
                          consumed=tuple(state["consumed"]), contracts=tuple(sorted(contracts.items())))


def close_position(state, position, price, now, reason, ambiguous=False):
    candidate = TradeCandidate.from_dict(position["candidate"])
    exposure = Exposure(**position["exposure"])
    policy = ExecutionPolicy.from_dict(position["policy"])
    product = instrument(candidate.symbol)
    sign = 1 if candidate.direction == "LONG" else -1
    fill = price-sign*policy.slippage_ticks*product.tick_size
    gross = (fill-exposure.entry)*sign*product.point_value*exposure.quantity
    costs = 2*policy.commission_per_side*exposure.quantity
    net = gross-costs
    trade = dict(strategy_id=candidate.strategy_id, strategy=candidate.strategy_name, symbol=candidate.symbol,
                 contract_id=candidate.contract_id, direction=candidate.direction, quantity=exposure.quantity,
                 entry=exposure.entry, exit=fill, initial_stop=candidate.stop, target=candidate.target,
                 entry_time=position["filled_at"], exit_time=stamp(now).isoformat(), session=candidate.session,
                 candidate_id=candidate.candidate_id, setup_id=candidate.setup_id, gross=gross, costs=costs, net=net,
                 reason=reason, ambiguous=ambiguous, planned_risk=position["planned_risk"], owner=candidate.strategy_id)
    state["trades"].append(trade)
    state["realized"] += net
    state["daily_realized"] += net
    state["consecutive_losses"] = state["consecutive_losses"]+1 if net < 0 else 0
    state["last_closed_at"] = stamp(now).isoformat()
    state["positions"].remove(position)


def record_decisions(state, candidates, decisions):
    known = {row["candidate_id"] for row in state["candidates"]}
    state["candidates"].extend(c.to_dict() for c in candidates if c.candidate_id not in known)
    state["decisions"].extend(decision.to_dict() for decision in decisions)


def advance_portfolio(old, candidates, observations, policy, now, *, contracts,
                      session_allowed=False, session_reason="Session unavailable", flatten=False):
    """Observations are actual sequenced trades. Pending entries wait for a later tick."""
    policy.validate()
    state = copy.deepcopy(old)
    if state["profile"] not in ("paper", "research"):
        raise ValueError("No broker portfolio simulation")
    now = stamp(now)
    if state.get("last_observed_at") and now < stamp(state["last_observed_at"]):
        raise ValueError("Portfolio observations cannot move backwards")
    day = trading_day(now)
    if state["day"] != day:
        state.update(day=day, daily_realized=0., daily_trades=0, consecutive_losses=0)
    previous_sequence, previous_time = state["cursor"], state.get("last_observed_at")
    for observation in observations:
        sequence, when = observation.get("sequence"), stamp(observation["time"])
        if type(sequence) is not int or sequence <= previous_sequence or when > now or (previous_time and when < stamp(previous_time)):
            raise ValueError("Trade sequence must be unique, increasing, causal and restart-safe")
        price, symbol, contract = observation.get("price"), observation.get("symbol"), observation.get("contract_id")
        product = instrument(symbol)
        if not finite(price) or price <= 0 or abs(price/product.tick_size-round(price/product.tick_size)) > 1e-6 or not contract:
            raise ValueError("Invalid actual-contract trade observation")
        previous_sequence, previous_time = sequence, when.isoformat()
        state["marks"][symbol] = dict(price=price, time=when.isoformat(), contract_id=contract)
        if trading_day(when) != state["day"]:
            raise ValueError("Advance portfolio in chronological session batches")
        for position in list(state["positions"]):
            exposure = position["exposure"]
            if exposure["symbol"] != symbol or exposure["contract_id"] != contract:
                continue
            candidate = TradeCandidate.from_dict(position["candidate"])
            long = candidate.direction == "LONG"
            if flatten or position.get("pending_exit"):
                reason = position.get("pending_exit") or "Scheduled flatten / next observed price"
                close_position(state, position, price, when, reason, ambiguous=reason.startswith("Data gap"))
            elif price <= exposure["stop"] if long else price >= exposure["stop"]:
                close_position(state, position, price, when, "Protective stop / observed trade")
            elif candidate.management_mode not in (MODE, "trailing") and (price >= candidate.target if long else price <= candidate.target):
                close_position(state, position, price, when, "Target / observed trade")
        for pending in list(state["pending"]):
            candidate = TradeCandidate.from_dict(pending["candidate"])
            if candidate.symbol != symbol or candidate.contract_id != contract or when <= stamp(pending["selected_at"]):
                continue
            state["pending"].remove(pending)
            frozen = ExecutionPolicy.from_dict(pending["policy"])
            fill = price+(1 if candidate.direction == "LONG" else -1)*frozen.slippage_ticks*product.tick_size
            executable = candidate.at_price(fill, when)
            entry_allowed = session_allowed and not flatten and (state["profile"] != "paper" or policy.paper_enabled)
            facts = state_at(state, frozen, when, contracts=contracts, session_allowed=entry_allowed, session_reason=session_reason if entry_allowed else "Paper entries disabled or session blocked before fill")
            # The reservation owns the consumed setup, but all other checks are repeated.
            facts = replace(facts, consumed=tuple(key for key in facts.consumed if key != candidate.setup_id))
            decisions = evaluate([executable], facts, frozen, when.isoformat(), scope="paper")
            current_decisions = evaluate([executable], facts, policy, when.isoformat(), scope="paper")
            decision, current_decision = decisions[0], current_decisions[0]
            quantity = min(pending["exposure"]["quantity"], decision.quantity, current_decision.quantity)
            final_decision = decision if not decision.selected else current_decision if not current_decision.selected else replace(
                decision, quantity=quantity, planned_risk=max(planned_risk(executable, quantity, frozen), planned_risk(executable, quantity, policy)),
                reasons=("Frozen and current paper permissions, capacity and fill geometry revalidated",))
            record_decisions(state, [executable], [final_decision])
            if decision.selected and current_decision.selected:
                exposure = Exposure(symbol, contract, candidate.direction, quantity, fill, candidate.stop,
                                    candidate.strategy_id, candidate.candidate_id)
                state["positions"].append(dict(candidate=candidate.to_dict(), exposure=exposure.__dict__,
                    policy=frozen.to_dict(), filled_at=when.isoformat(), planned_risk=final_decision.planned_risk,
                    management_state={**json.loads(candidate.risk_json), "signal": candidate.direction, "entry": fill,
                                      "initial_stop": candidate.stop, "stop": candidate.stop, "target": candidate.target,
                                      "exit_mode": candidate.management_mode, "tick_size": product.tick_size,
                                      "management_started_at": when.isoformat()}, pending_exit=None))
                state["daily_trades"] += 1
    state["cursor"], state["last_observed_at"] = previous_sequence, previous_time
    # Expiry consumes the intent, but never creates a synthetic fill.
    for pending in list(state["pending"]):
        if stamp(pending["candidate"]["expires_at"]) <= now:
            state["pending"].remove(pending)
            candidate = TradeCandidate.from_dict(pending["candidate"])
            facts = state_at(state, policy, now, contracts=contracts, session_allowed=session_allowed, session_reason=session_reason)
            record_decisions(state, [candidate], evaluate([candidate], facts, policy, now.isoformat(), scope="paper"))
    supplied = tuple(candidates)
    if supplied:
        facts = state_at(state, policy, now, contracts=contracts, session_allowed=session_allowed and not flatten, session_reason=session_reason)
        if not policy.paper_enabled and state["profile"] == "paper":
            facts = replace(facts, paused=True)
        decisions = evaluate(supplied, facts, policy, now.isoformat(), scope="paper" if state["profile"] == "paper" else "historical")
        record_decisions(state, supplied, decisions)
        by_id = {candidate.candidate_id: candidate for candidate in supplied}
        for decision in decisions:
            if not decision.selected:
                continue
            candidate = by_id[decision.candidate_id]
            exposure = Exposure(candidate.symbol, candidate.contract_id, candidate.direction, decision.quantity,
                                candidate.price, candidate.stop, candidate.strategy_id, candidate.candidate_id, status="reserved")
            state["pending"].append(dict(candidate=candidate.to_dict(), exposure=exposure.__dict__,
                                          policy=policy.to_dict(), selected_at=now.isoformat(), planned_risk=decision.planned_risk))
            state["consumed"].append(candidate.setup_id)
    marked = state["realized"]
    for position in state["positions"]:
        exposure = Exposure(**position["exposure"])
        mark = state["marks"].get(exposure.symbol)
        if mark and mark["contract_id"] == exposure.contract_id:
            marked += (mark["price"]-exposure.entry)*(1 if exposure.direction == "LONG" else -1)*instrument(exposure.symbol).point_value*exposure.quantity
            marked -= ExecutionPolicy.from_dict(position["policy"]).commission_per_side*exposure.quantity
    state["equity"].append(marked)
    return state


def portfolio_summary(state):
    decisions = state["decisions"]
    counts = {}
    for row in decisions:
        counts[row["eligibility"]] = counts.get(row["eligibility"], 0)+1
    used = 0.
    for position in (*state["positions"], *state["pending"]):
        exposure = Exposure(**position["exposure"])
        frozen = ExecutionPolicy.from_dict(position["policy"])
        used += exposure.risk+exposure.quantity*(2*frozen.commission_per_side+2*frozen.slippage_ticks*instrument(exposure.symbol).tick_value)+frozen.protective_buffer
    return dict(metrics=statistics(state["trades"], equity=state["equity"]), strategies=breakdown(state["trades"], "strategy"),
                directions=breakdown(state["trades"], "direction"), sessions=breakdown(state["trades"], "session"), months=breakdown(state["trades"], "month"),
                rejection_counts=counts, conflict_rate=counts.get("CONFLICTED", 0)/len(decisions) if decisions else 0.,
                open_positions=len(state["positions"]), pending=len(state["pending"]), realized=state["realized"],
                unrealized=state["equity"][-1]-state["realized"], planned_open_risk=used)


def manage_completed(state, symbol, minutes, now):
    """Same frozen owner and existing exit implementation; changes apply next tick."""
    from goxtrade.research.backtest import manage_after_close
    import pandas as pd
    closed = minutes.loc[pd.to_datetime(minutes["time"], utc=True)+pd.Timedelta(minutes=1) <= pd.Timestamp(now)]
    if closed.empty:
        return
    for position in state["positions"]:
        exposure = position["exposure"]
        if exposure["symbol"] != symbol or minutes.attrs.get("contract_id") != exposure["contract_id"]:
            continue
        active = position["management_state"]
        if active["exit_mode"] == "trailing" and "trail_ticks" not in active:
            position["pending_exit"] = "Incomplete frozen trailing configuration; next observed close"
            continue
        reason = manage_after_close(active, closed.iloc[-1], closed, pd.Timestamp(now))
        long = exposure["direction"] == "LONG"
        exposure["stop"] = max(exposure["stop"], active["stop"]) if long else min(exposure["stop"], active["stop"])
        if reason:
            position["pending_exit"] = reason
