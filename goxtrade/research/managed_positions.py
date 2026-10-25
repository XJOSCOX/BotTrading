"""Post-entry adapters. Existing positions without an explicit snapshot stay legacy."""
import copy
import json
from dataclasses import replace

from goxtrade.execution import trade_manager as manager
from goxtrade.execution.profit_policy import ProfitPolicy
from goxtrade.execution.trade_analytics import analytics, mark
from goxtrade.execution.trade_candidate import frozen_json
from goxtrade.market.instruments import instrument, round_tick


def with_exit_policy(candidates, policy):
    if policy is None or not policy.enabled:
        return candidates
    policy.validate()
    return [replace(candidate, risk_json=frozen_json({**json.loads(candidate.risk_json), "profit_policy": policy.to_dict()})) for candidate in candidates]


def attach(position):
    candidate, exposure = position["candidate"], position["exposure"]
    values = json.loads(candidate["risk_json"])
    policy = values.get("profit_policy")
    if not policy or not policy.get("enabled"):
        return
    position["trade_management"] = manager.open_trade(trade_id=candidate["candidate_id"], symbol=candidate["symbol"],
        contract_id=candidate["contract_id"], direction=candidate["direction"], entry=exposure["entry"], quantity=exposure["quantity"],
        stop=exposure["stop"], target=candidate["target"], entered_at=position["filled_at"], policy=ProfitPolicy.from_dict(policy),
        commission_per_side=position["policy"]["commission_per_side"], slippage_ticks=position["policy"]["slippage_ticks"],
        baseline=position["management_state"], strategy=candidate["strategy_name"], session=candidate["session"], structural_target=candidate["target"])
    position["accounted_exit_fills"] = 0


def book_portfolio(state, position):
    managed = position["trade_management"]
    fills = managed["fills"]
    for fill in fills[position.get("accounted_exit_fills", 0):]:
        state["realized"] += fill["net"]
        state["daily_realized"] += fill["net"]
    position["accounted_exit_fills"] = len(fills)
    position["exposure"].update(quantity=managed["remaining"], stop=managed["stop"])
    if managed["remaining"]:
        return
    candidate = position["candidate"]
    diagnostics = analytics(managed)
    net = sum(fill["net"] for fill in fills)
    state["trades"].append(dict(strategy_id=candidate["strategy_id"], strategy=candidate["strategy_name"],
        symbol=candidate["symbol"], contract_id=candidate["contract_id"], direction=candidate["direction"],
        quantity=managed["original_quantity"], entry=managed["entry"], exit=sum(fill["quantity"]*fill["price"] for fill in fills)/managed["original_quantity"],
        entry_time=managed["entered_at"], exit_time=managed["last_time"], initial_stop=managed["initial_stop"], target=managed["target"],
        gross=managed["realized_gross"], costs=diagnostics["fees"], net=net, reason=managed["last_exit_reason"],
        session=candidate["session"], candidate_id=candidate["candidate_id"], setup_id=candidate["setup_id"],
        holding_seconds=diagnostics["holding_seconds"], partial_fills=fills, management_analytics=diagnostics, exit_policy=managed["policy"]))
    state["last_closed_at"] = managed["last_time"]
    state["consecutive_losses"] = state["consecutive_losses"]+1 if net < 0 else 0
    state["positions"].remove(position)


def observe_portfolio(state, position, price, now, *, minutes=(), force_reason=None, defer_structure=False):
    managed = position["trade_management"]
    managed = manager.observe(managed, price, now, managed["last_sequence"]+1, position["exposure"]["contract_id"], minutes=minutes)
    if force_reason and managed["remaining"] and not managed["pending_exit"]:
        manager.propose_exit(managed, managed["remaining"], force_reason, now, managed["last_sequence"])
    if not (defer_structure and managed.get("pending_exit") and managed["pending_exit"]["reason"] == "Structure break"):
        managed = manager.simulate_exit(managed, now)
    position["trade_management"] = managed
    book_portfolio(state, position)


def completed_bar(state, position, bar, known, closed_at):
    """OHLC has no intrabar ordering: old-stop first; new trails apply next bar."""
    managed = position["trade_management"]
    sign = managed["sign"]
    old_stop = managed["stop"]
    stopped = bar["low"] <= old_stop if sign > 0 else bar["high"] >= old_stop
    if stopped:
        price = min(bar["open"], old_stop) if sign > 0 else max(bar["open"], old_stop)
        managed["ohlc_ambiguity"] = "Excursion after intrabar exit is unknown; no post-exit extremes counted"
        observe_portfolio(state, position, float(price), closed_at, force_reason="Protective stop / OHLC stop first")
        return
    # No old stop breach: the position survives the bar until a profit exit, if any.
    target = managed["target"]
    policy = ProfitPolicy.from_dict(managed["policy"])
    favorable = float(bar["high"] if sign > 0 else bar["low"])
    fixed = policy.mode == "fixed" or (policy.mode in ("hybrid", "breakeven", "profit_lock") and policy.final_target_enabled) or (policy.mode == "baseline" and managed["baseline"].get("exit_mode") not in ("structure-v1", "trailing"))
    hit_final = (favorable-target)*sign >= 0 and fixed
    if hit_final:
        observe_portfolio(state, position, float(target), closed_at, force_reason="Fixed profit target / OHLC")
        return
    for index, (milestone, quantity) in enumerate(policy.partial_targets):
        level = round_tick(managed["entry"]+sign*milestone*managed["initial_risk_points"], instrument(managed["symbol"]).tick_size, up=sign > 0)
        if managed["original_quantity"] > 1 and (favorable-level)*sign >= 0 and index not in managed["completed_partials"]:
            observe_portfolio(state, position, float(level), closed_at)
            if position not in state["positions"]:
                return
            managed = position["trade_management"]
            # OHLC cannot establish a trail-before-reversal ordering in this bar.
            managed["stop"] = old_stop
    # Mark bounds are labeled OHLC estimates, not ordered ticks. Tightening occurs at close.
    mark(managed, favorable, closed_at)
    mark(managed, float(bar["low"] if sign > 0 else bar["high"]), closed_at)
    managed["excursion_provenance"] = "Completed OHLC bounds while position survived; intrabar path unknown"
    observe_portfolio(state, position, float(bar["close"]), closed_at, minutes=known.to_dict("records"), defer_structure=True)


def single_paper_tick(active, price, when, symbol, spec, sim, minutes, policy_snapshot=None):
    """Reuse the engine for opt-in strategy paper; return one completed episode."""
    if "trade_management" not in active:
        if policy_snapshot is None:
            return None
        active["trade_management"] = manager.open_trade(trade_id=active["unique_setup_id"], symbol=symbol,
            contract_id=active["contract_id"], direction=active["signal"], entry=active["entry"], quantity=active["quantity"],
            stop=active["initial_stop"], target=active["target"], entered_at=active["entry_time"],
            policy=ProfitPolicy.from_dict(policy_snapshot), commission_per_side=sim.commission_per_side,
            slippage_ticks=sim.slippage_ticks, baseline=active, strategy=spec.name, session=active.get("session", "unknown"), structural_target=active["target"])
    managed = active["trade_management"]
    managed = manager.observe(managed, price, when, managed["last_sequence"]+1, active["contract_id"], minutes=minutes.to_dict("records"))
    from goxtrade.market.trading_schedule import execution_schedule
    if execution_schedule(when.to_pydatetime())["flatten"] and not managed["pending_exit"]:
        manager.propose_exit(managed, managed["remaining"], "Scheduled paper flatten", when, managed["last_sequence"])
    managed = manager.simulate_exit(managed, when)
    active["trade_management"] = managed
    active["stop"] = managed["stop"]
    if managed["remaining"]:
        return None
    details = analytics(managed)
    fills = managed["fills"]
    return dict(strategy_id=spec.id, strategy=spec.name, symbol=instrument(symbol).symbol,
        direction=active["signal"], contract_id=active["contract_id"], entry=managed["entry"],
        exit=sum(fill["quantity"]*fill["price"] for fill in fills)/managed["original_quantity"],
        entry_time=active["entry_time"], exit_time=managed["last_time"], quantity=managed["original_quantity"],
        gross=managed["realized_gross"], costs=details["fees"], net=details["realized_net"], session=active.get("session"),
        reason=managed["last_exit_reason"], unique_setup_id=active["unique_setup_id"], partial_fills=fills,
        management_analytics=details, exit_policy=managed["policy"], test_type="forward_paper", ambiguous=False,
        detection_sequence=active["detection_sequence"], entry_sequence=active["entry_sequence"])
