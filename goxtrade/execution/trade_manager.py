"""Pure post-entry engine: proposals and reconciled fills, never broker requests."""
import copy
import math
from datetime import timedelta

from goxtrade.execution.partial_exits import partial_plan
from goxtrade.execution.profit_policy import ProfitPolicy
from goxtrade.execution.trade_candidate import digest, finite, stamp
from goxtrade.execution.trade_analytics import mark, analytics
from goxtrade.market.instruments import instrument, round_tick, validate_contract_instrument


def open_trade(*, trade_id, symbol, contract_id, direction, entry, quantity, stop, target, entered_at,
               policy, commission_per_side, slippage_ticks, baseline=None, strategy="unknown", session="unknown", structural_target=None):
    policy.validate()
    product = instrument(symbol)
    validate_contract_instrument(symbol, contract_id)
    sign = 1 if direction == "LONG" else -1
    if direction not in ("LONG", "SHORT") or type(quantity) is not int or not 1 <= quantity <= 4:
        raise ValueError("Explicit direction and whole-contract quantity 1-4 required")
    if not all(finite(v) and v > 0 for v in (entry, stop, target)) or (entry-stop)*sign <= 0 or (target-entry)*sign <= 0:
        raise ValueError("Actual fill invalidates original structural stop/target")
    if not trade_id or not contract_id or not finite(commission_per_side) or commission_per_side < 0 or not finite(slippage_ticks) or slippage_ticks < 0 or slippage_ticks % 1:
        raise ValueError("Explicit identity and cost assumptions required")
    slippage_ticks = int(slippage_ticks)
    when = stamp(entered_at).isoformat()
    risk = (entry-stop)*sign
    original_target = target
    for level in (stop, target):
        if abs(level/product.tick_size-round(level/product.tick_size)) > 1e-6:
            raise ValueError("Protective stop/target must use the instrument tick grid")
    if policy.mode != "baseline":
        distance = {"rr": risk*policy.target_r, "ticks": product.tick_size*policy.target_ticks, "points": policy.target_points}.get(policy.target_method)
        if distance is not None:
            target = round_tick(entry+sign*distance, product.tick_size, up=sign > 0)
        elif policy.target_method == "structural":
            if not finite(structural_target) or (structural_target-entry)*sign <= 0:
                raise ValueError("Explicit structural profit target required")
            target = structural_target
    if abs(target/product.tick_size-round(target/product.tick_size)) > 1e-6:
        raise ValueError("Structural target must use the instrument tick grid")
    cost_buffer = 2*commission_per_side/product.point_value if policy.break_even_cover_costs else 0.
    break_even_level = round_tick(entry+sign*(cost_buffer+policy.break_even_buffer_ticks*product.tick_size), product.tick_size, up=sign > 0)
    initial = copy.deepcopy(baseline or dict(signal=direction, entry=entry, initial_stop=stop, stop=stop, target=target, exit_mode="fixed"))
    initial.update(signal=direction, entry=entry, initial_stop=stop, stop=stop, management_started_at=when, tick_size=product.tick_size)
    state = dict(version="trade-v1", trade_id=trade_id, symbol=product.symbol, contract_id=contract_id,
        strategy=strategy, session=session, direction=direction, sign=sign, entry=entry, original_quantity=quantity,
        remaining=quantity, initial_stop=stop, stop=stop, initial_target=original_target, target=target, break_even_level=break_even_level,
        entered_at=when, last_time=when, last_sequence=0, high=entry, low=entry, initial_risk_points=risk,
        policy=policy.to_dict(), policy_fingerprint=digest(policy.to_dict()), baseline=initial,
        status="PROTECTED", protection_status="SOFTWARE / SIMULATED STOP - not broker-confirmed",
        pending_exit=None, fills=[], completed_partials=[], blocked_partials=[], realized_gross=0., entry_fee=commission_per_side,
        exit_fees=0., slippage_ticks=slippage_ticks, slippage_dollars=0., peak_mark_gross=0.,
        peak_mark_net=-2*quantity*commission_per_side, peak_at=when, target_touched=False, decisions=[], locked_stop=None)
    mark(state, entry, when)
    return state


def completed_features(minutes, now, policy, entered_at):
    """Only complete, as-of-available UTC bars; no future highs/lows enter a trail."""
    from goxtrade.strategies.stop_policy import aggregate_minutes
    rows, seen = [], set()
    for row in minutes:
        opened = stamp(row["time"])
        if opened in seen:
            raise ValueError("Duplicate management minutes")
        seen.add(opened)
        if opened.timestamp()+60 > stamp(now).timestamp() or row.get("complete", True) is not True:
            continue
        if row.get("asof_time") and stamp(row["asof_time"]) > stamp(now):
            continue
        if not all(finite(row.get(k)) and row[k] > 0 for k in ("high", "low", "close")) or row["high"] < row["low"] or not row["low"] <= row["close"] <= row["high"]:
            raise ValueError("Invalid management OHLC")
        rows.append({**row, "time": opened.isoformat(), "closed_at": (opened+timedelta(minutes=1)).isoformat()})
    bars = aggregate_minutes(sorted(rows, key=lambda r: r["time"]), policy.management_minutes)
    recent = bars[-15:]
    contiguous = len(recent) == 15 and all(stamp(b["time"])-stamp(a["time"]) == timedelta(minutes=policy.management_minutes) for a, b in zip(recent, recent[1:]))
    if recent and stamp(now).timestamp()-stamp(recent[-1]["closed_at"]).timestamp() >= policy.management_minutes*60:
        contiguous = False
    atr = sum(max(b["high"]-b["low"], abs(b["high"]-a["close"]), abs(b["low"]-a["close"])) for a, b in zip(recent, recent[1:]))/14 if contiguous else None
    entered = stamp(entered_at)
    owned = [b for b in bars if stamp(b["time"]) >= entered]
    tail = owned[-policy.structure_lookback:]
    structure = tail if len(tail) == policy.structure_lookback and all((stamp(b["time"])-stamp(a["time"])).total_seconds() == policy.management_minutes*60 for a, b in zip(tail, tail[1:])) else []
    return dict(atr=atr, structure=structure, bars=bars, minutes=rows)


def propose_exit(state, quantity, reason, when, sequence, partial_index=None):
    if state["pending_exit"] or state["remaining"] == 0:
        return
    identity = digest(dict(trade=state["trade_id"], sequence=sequence, reason=reason, partial=partial_index))
    state["pending_exit"] = dict(id=identity, quantity=quantity, filled=0, reason=reason, observed_at=stamp(when).isoformat(),
                                 sequence=sequence, partial_index=partial_index, state="INTENT")
    state["status"] = "EXIT_PENDING"


def observe(old, price, when, sequence, contract_id, *, observed_at=None, minutes=()):
    state = copy.deepcopy(old)
    if state["remaining"] == 0:
        return state
    policy = ProfitPolicy.from_dict(state["policy"])
    if digest(policy.to_dict()) != state["policy_fingerprint"]:
        raise ValueError("Frozen exit policy was altered")
    if type(sequence) is not int or sequence <= state["last_sequence"]:
        return state
    current, known = stamp(when), stamp(observed_at or when)
    if contract_id != state["contract_id"] or not finite(price) or price <= 0 or current < stamp(state["last_time"]) or not 0 <= (known-current).total_seconds() <= policy.max_data_age_seconds:
        state["blocked_reason"] = "Wrong contract, stale/future or invalid trade observation"
        return state
    product = instrument(state["symbol"])
    if abs(price/product.tick_size-round(price/product.tick_size)) > 1e-6:
        state["blocked_reason"] = "Trade observation is off the instrument tick grid"
        return state
    state.update(last_sequence=sequence, last_time=current.isoformat(), blocked_reason=None)
    mark(state, price, current)
    if state["remaining"] == 0 or state["pending_exit"]:
        return state
    long, sign = state["sign"] > 0, state["sign"]
    if (price-state["stop"])*sign <= 0:
        propose_exit(state, state["remaining"], "Protective stop", current, sequence)
        return state
    if (price-state["target"])*sign >= 0:
        state["target_touched"] = True
        fixed = policy.mode == "fixed" or (policy.mode in ("hybrid", "breakeven", "profit_lock") and policy.final_target_enabled)
        fixed |= policy.mode == "baseline" and state["baseline"].get("exit_mode") not in ("structure-v1", "trailing")
        if fixed:
            propose_exit(state, state["remaining"], "Fixed profit target", current, sequence)
            return state
    if policy.mode in ("partial", "hybrid"):
        partial = partial_plan(policy.partial_targets, state["original_quantity"], state["remaining"], state["current_r"], state["completed_partials"])
        if partial and partial.get("blocked"):
            if partial["index"] not in state["blocked_partials"]:
                state["blocked_partials"].append(partial["index"])
                state["decisions"].append(dict(time=current.isoformat(), reason=partial["reason"]))
        elif partial:
            propose_exit(state, partial["quantity"], "Partial profit milestone", current, sequence, partial["index"])
            return state
    levels = []
    if (policy.mode == "breakeven" or policy.break_even_enabled) and state["max_r"] >= policy.break_even_r:
        costs = 2*state["entry_fee"]/product.point_value if policy.break_even_cover_costs else 0.
        levels.append((round_tick(state["entry"]+sign*(costs+policy.break_even_buffer_ticks*product.tick_size), product.tick_size, up=long), "Break-even estimate"))
    if (policy.mode == "profit_lock" or policy.profit_lock_enabled) and state["max_r"] >= policy.profit_lock_r:
        level = state["entry"]+sign*state["mfe_points"]*policy.retain_fraction
        levels.append((round_tick(level, product.tick_size, up=not long), "Profit-lock fraction"))
    features = completed_features(minutes, current, policy, state["entered_at"]) if minutes else dict(atr=None, structure=[], bars=[], minutes=[])
    if policy.mode == "baseline":
        from goxtrade.research.backtest import manage_after_close
        import pandas as pd
        baseline = state["baseline"]
        baseline["stop"] = state["stop"]
        if baseline.get("exit_mode") in ("structure-v1", "trailing", "breakeven"):
            frame = pd.DataFrame(features["minutes"], columns=["time", "high", "low", "close"])
            if not frame.empty:
                frame["time"] = pd.to_datetime(frame["time"], utc=True)
                reason = manage_after_close(baseline, dict(close=price), frame, pd.Timestamp(current))
                if reason:
                    propose_exit(state, state["remaining"], reason, current, sequence)
            elif baseline.get("exit_mode") != "structure-v1":
                risk, favorable = state["initial_risk_points"], (price-state["entry"])*sign
                if baseline["exit_mode"] == "breakeven" and favorable >= risk*baseline.get("breakeven_r", 1):
                    baseline["stop"] = state["entry"]
                if baseline["exit_mode"] == "trailing" and favorable >= risk*baseline.get("trail_start_r", 1.5) and baseline.get("trail_ticks"):
                    baseline["stop"] = price-sign*baseline["trail_ticks"]*product.tick_size
            levels.append((baseline["stop"], "Frozen baseline management"))
    elif policy.mode in ("trailing", "partial", "hybrid") and state["max_r"] >= policy.trail_start_r:
        extreme = state["high"] if long else state["low"]
        if policy.trailing_method in ("fixed_ticks", "extreme"):
            levels.append((extreme-sign*policy.trail_ticks*product.tick_size, "Favorable-extreme tick trail"))
        elif policy.trailing_method == "atr" and features["atr"] is not None:
            levels.append((extreme-sign*features["atr"]*policy.atr_multiple, "Completed-candle ATR trail"))
        elif policy.trailing_method == "adaptive":
            from goxtrade.strategies.adaptive_exit import update_exit
            owned = state["baseline"]
            owned.update(stop=state["stop"], management_minutes=policy.management_minutes,
                         structure_lookback=policy.structure_lookback, trail_start_r=policy.trail_start_r)
            reason = update_exit(owned, features["bars"], dict(event_time=current.isoformat()))
            if reason:
                propose_exit(state, state["remaining"], reason, current, sequence)
            levels.append((owned["stop"], "Frozen adaptive structure management"))
        elif policy.trailing_method == "structure" and features["structure"]:
            boundary = min(b["low"] for b in features["structure"]) if long else max(b["high"] for b in features["structure"])
            levels.append((boundary-sign*product.tick_size, "Completed structure trail"))
    for level, reason in levels:
        level = round_tick(level, product.tick_size, up=not long)
        if (level-state["stop"])*sign > 0 and (price-level)*sign > 0:
            state["stop"], state["locked_stop"] = level, level
            state["status"] = "PROFIT_LOCKED" if (level-state["entry"])*sign >= 0 else "PROFIT_MONITORING"
            state["decisions"].append(dict(time=current.isoformat(), stop=level, reason=reason, protection="software only"))
    return state


def reconcile_fill(old, *, intent_id, fill_id, quantity, price, when, fee_per_contract=None):
    state = copy.deepcopy(old)
    if fill_id in {fill["id"] for fill in state["fills"]}:
        return state
    intent = state["pending_exit"]
    if not intent or intent["id"] != intent_id or type(quantity) is not int or not 1 <= quantity <= min(state["remaining"], intent["quantity"]-intent["filled"]):
        raise ValueError("Exit fill does not match outstanding whole-contract intent")
    if not fill_id or not finite(price) or price <= 0 or stamp(when) < stamp(intent["observed_at"]) or stamp(when) < stamp(state["last_time"]):
        raise ValueError("Invalid observed exit fill")
    fee = state["entry_fee"] if fee_per_contract is None else fee_per_contract
    if not finite(fee) or fee < 0:
        raise ValueError("Invalid exit commission")
    product = instrument(state["symbol"])
    gross = (price-state["entry"])*state["sign"]*product.point_value*quantity
    state["fills"].append(dict(id=fill_id, quantity=quantity, price=price, time=stamp(when).isoformat(), reason=intent["reason"],
                               gross=gross, costs=(state["entry_fee"]+fee)*quantity, net=gross-(state["entry_fee"]+fee)*quantity))
    state["remaining"] -= quantity
    state["realized_gross"] += gross
    state["exit_fees"] += fee*quantity
    state["slippage_dollars"] += abs(price-state["current_price"])*product.point_value*quantity
    intent["filled"] += quantity
    state["last_exit_reason"] = intent["reason"]
    state["last_time"] = stamp(when).isoformat()
    if intent["filled"] == intent["quantity"]:
        if intent["partial_index"] is not None:
            state["completed_partials"].append(intent["partial_index"])
        state["pending_exit"] = None
    state["status"] = "CLOSED" if state["remaining"] == 0 else "EXIT_PENDING" if state["pending_exit"] else "PROFIT_MONITORING"
    mark(state, state["current_price"], when)
    return state


def simulate_exit(state, when):
    """Deterministic observed-price plus adverse-slippage fill, never a broker call."""
    intent = state["pending_exit"]
    if not intent:
        return state
    product = instrument(state["symbol"])
    price = state["current_price"]-state["sign"]*state["slippage_ticks"]*product.tick_size
    return reconcile_fill(state, intent_id=intent["id"], fill_id="paper:"+intent["id"],
                          quantity=intent["quantity"]-intent["filled"], price=price, when=when)
