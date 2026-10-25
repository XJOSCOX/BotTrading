"""Observed excursion and episode giveback, separate from executable/broker P&L."""
from goxtrade.execution.trade_candidate import stamp
from goxtrade.market.instruments import instrument


def mark(state, price, when):
    sign = state["sign"]
    product = instrument(state["symbol"])
    state["high"] = max(state["high"], price)
    state["low"] = min(state["low"], price)
    favorable = max(0., (state["high"]-state["entry"])*sign if sign > 0 else (state["entry"]-state["low"]))
    adverse = max(0., state["entry"]-state["low"] if sign > 0 else state["high"]-state["entry"])
    state["mfe_points"], state["mae_points"] = favorable, adverse
    state["max_r"] = favorable/state["initial_risk_points"]
    state["current_r"] = (price-state["entry"])*sign/state["initial_risk_points"]
    unrealized = (price-state["entry"])*sign*product.point_value*state["remaining"]
    gross = state["realized_gross"]+unrealized
    expected_fees = state["entry_fee"]*state["original_quantity"]+state["exit_fees"]+state["entry_fee"]*state["remaining"]
    net = gross-expected_fees
    if gross >= state["peak_mark_gross"]:
        state["peak_mark_gross"], state["peak_at"] = gross, stamp(when).isoformat()
    state["peak_mark_net"] = max(state["peak_mark_net"], net)
    state.update(current_price=price, marked_unrealized_gross=unrealized, marked_episode_gross=gross,
                 marked_episode_net=net, liquidation_estimate_net=net-state["remaining"]*state["slippage_ticks"]*product.tick_value,
                 holding_seconds=max(0., (stamp(when)-stamp(state["entered_at"])).total_seconds()),
                 giveback_gross=max(0., state["peak_mark_gross"]-gross), giveback_net=max(0., state["peak_mark_net"]-net))


def analytics(state):
    product = instrument(state["symbol"])
    risk = state["initial_risk_points"]*product.point_value*state["original_quantity"]
    net = state["realized_gross"]-state["entry_fee"]*state["original_quantity"]-state["exit_fees"]
    final = state["remaining"] == 0
    giveback = max(0., state["peak_mark_gross"]-state["realized_gross"]) if final else state["giveback_gross"]
    categories = []
    if final and net < 0:
        categories.extend(f"Reached {threshold:g}R then closed negative" for threshold in (1., 1.5, 2.) if state["max_r"] >= threshold)
    if state.get("target_touched") and state["policy"]["mode"] == "baseline" and state["baseline"].get("exit_mode") in ("structure-v1", "trailing"):
        categories.append("Reference target touched; adaptive policy retained position")
    return dict(mfe_points=state["mfe_points"], mae_points=state["mae_points"],
                mfe_dollars=state["mfe_points"]*product.point_value*state["original_quantity"],
                mae_dollars=state["mae_points"]*product.point_value*state["original_quantity"],
                maximum_marked_profit=state["peak_mark_gross"], maximum_marked_net=state["peak_mark_net"],
                realized_gross=state["realized_gross"], realized_net=net if final else None,
                profit_giveback=giveback, giveback_percent=100*giveback/state["peak_mark_gross"] if state["peak_mark_gross"] > 0 else None,
                current_r=state["current_r"], maximum_r=state["max_r"], captured_r=net/risk if final else None,
                capture_percent=100*state["realized_gross"]/state["peak_mark_gross"] if final and state["peak_mark_gross"] > 0 else None,
                seconds_peak_to_exit=max(0., (stamp(state["last_time"])-stamp(state["peak_at"])).total_seconds()) if final else None,
                holding_seconds=state["holding_seconds"], fees=state["entry_fee"]*state["original_quantity"]+state["exit_fees"],
                slippage_dollars=state["slippage_dollars"], slippage_scope="Exit fill deviation from observed mark; entry slippage embedded in fill basis", diagnostic_categories=categories,
                policy=state["policy"], exit_reason=state.get("last_exit_reason"), protection_status=state["protection_status"],
                scope="Simulated fills / observed marks; not broker-realized profits")
