import streamlit as st
from datetime import datetime, timezone
import practice_executor as executor
import practice_history
import live_theme
import practice_safety
from zoneinfo import ZoneInfo


@st.fragment(run_every="3s")
def render_trade_history():
    st.subheader("Activity & results")
    state, fills = practice_history.snapshot()
    if state.get("error"):
        st.warning("History refresh unavailable. Showing saved fills.")
    updated = state.get("updated_at")
    stamp = datetime.fromisoformat(updated).astimezone(ZoneInfo("America/Chicago")).strftime("%b %d, %H:%M:%S CT") if updated else "Waiting for broker"
    st.caption(f"Practice account / Updated {stamp}")
    if updated:
        positions, orders = state.get("positions", []), state.get("orders", [])
        st.write(f"Broker snapshot: {len(positions)} open positions / {len(orders)} working orders")
        if positions:
            st.dataframe([{"Contract": r.get("contractId"), "Contracts": r.get("size"),
                           "Average entry": r.get("averagePrice")} for r in positions],
                         hide_index=True, width="stretch")
        if orders:
            st.dataframe([{"Order": r.get("id"), "Contract": r.get("contractId"),
                           "Type": r.get("type"), "Contracts": r.get("size"),
                           "Stop price": r.get("stopPrice")} for r in orders],
                         hide_index=True, width="stretch")
    if updated and (datetime.now(timezone.utc) - datetime.fromisoformat(updated)).total_seconds() > 45:
        st.warning("Trade history is stale.")
    if not fills:
        st.info("No Practice fills recorded." if updated else "Loading Practice fills.")
        return
    import executed_results
    matched = executed_results.results(executor.snapshot()[2], fills)
    summary = executed_results.summary(matched)
    win, loss, pnl, fees = st.columns(4)
    win.metric("Winning exits", summary["wins"])
    loss.metric("Losing exits", summary["losses"])
    pnl.metric("Bot net P&L", f"${summary['net']:,.2f}")
    fees.metric("Bot costs", f"${sum(r['costs'] for r in matched.values()):,.2f}")
    st.caption("Summary: matched closed bot trades only. Manual trades, connection tests and watch signals excluded.")
    rows = []
    for row in fills:
        rows.append({"Time (CT)": datetime.fromisoformat(row["creationTimestamp"]).astimezone(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d %H:%M:%S"),
                     "Contract": row["contractId"], "Side": {0: "Buy", 1: "Sell"}.get(row.get("side"), "Unknown"),
                     "Contracts": row.get("size"), "Fill price": row.get("price"),
                     "Realized P&L": row.get("profitAndLoss"), "Fees": row.get("fees"),
                     "Voided": row.get("voided", False), "Order": row.get("orderId")})
    st.dataframe(live_theme.table(rows), hide_index=True, width="stretch", height=min(300, 35 * len(rows) + 38),
                 column_config={"Fill price": st.column_config.NumberColumn(format="%.2f"),
                                "Realized P&L": st.column_config.NumberColumn(format="$%.2f"),
                                "Fees": st.column_config.NumberColumn(format="$%.2f")})
    st.caption("Account-wide broker fills, including pre-bot trades. Voided fills excluded. Blank P&L = unrealized entry fill.")


@st.fragment(run_every="3s")
def render_practice():
    st.subheader("Execution")
    settings, runtime, jobs = executor.snapshot()
    st.caption(f"{executor.ACCOUNT_NAME}")
    updated = runtime.get("updated_at")
    fresh = updated and (datetime.now(timezone.utc) - datetime.fromisoformat(updated)).total_seconds() < 15
    live_theme.status(settings.get("enabled"), fresh, runtime.get("message", "Worker starting"))
    if not fresh:
        st.warning("Practice worker is not updating. Keep the live-feed service running.")
    unresolved = any(j["state"] not in ("Closed", "Rejected") for j in jobs)
    gate = practice_safety.snapshot()
    st.text(f"Account loss lock: USD 500 / Realized loss: USD {gate.get('loss', 0):,.2f}")
    if gate.get("locked"):
        st.error("$500 loss lock. Confirmation required before trading can resume.")
    with st.form("practice_start"):
        enable_mym = st.checkbox("Enable MYM trading", value=settings.get("enable_mym", False))
        columns = st.columns(3)
        quantities = {symbol: col.number_input(symbol, 1, 4,
                                               settings.get("quantities", {}).get(symbol, 2), step=1)
                      for symbol, col in zip(("MNQ", "MES", "MYM"), columns)}
        confirmed = st.checkbox("Practice is isolated from all copiers, uses Auto OCO Brackets, and has no manual trading.")
        acknowledge = st.checkbox("I acknowledge the $500 loss and authorize resetting the loss baseline and resuming Practice.") if gate.get("locked") else False
        start = st.form_submit_button("Start Practice", disabled=bool(settings.get("enabled")) or unresolved or not fresh, icon=":material/play_arrow:")
        if start:
            try:
                executor.arm(500, 500, confirmed, quantities, acknowledge_loss=acknowledge, enable_mym=enable_mym)
                st.success("Practice armed for new signals. Existing alerts will not be entered.")
                st.rerun()
            except Exception as error:
                st.error(str(error) if isinstance(error, ValueError) else "Practice preflight failed. Check account and API connection.")
    if st.button("Pause new entries", icon=":material/pause:", disabled=not settings.get("enabled")):
        executor.pause()
        st.rerun()
    st.caption("Practice only. Strategy-based stops and exits. Selected contracts per entry; no dollar-based size reduction.")
    st.caption("One position per symbol / First entry: selected size / Additional symbols: 1 contract each / Cooldown after confirmed close")
    st.caption("Trading: MNQ, MES" + (", MYM" if settings.get("enable_mym") else " / MYM watch only"))
    with st.expander("Risk details"):
        st.caption("Original broker stops remain; signal exits request a close. The USD 500 lock uses cumulative realized account balance loss from its saved baseline, not unrealized P&L. It persists across runs until explicitly reset. A trade, fees or slippage can take losses beyond USD 500.")


@st.fragment(run_every="3s")
def render_order_attempts():
    _, _, jobs = executor.snapshot()
    st.subheader("Bot order history")
    if not jobs:
        st.caption("No bot orders submitted.")
    if jobs:
        st.dataframe(live_theme.table([{"Alert": j["alert_id"], "Micro": j["symbol"], "Contracts": j["quantity"],
                       "Submitted (CT)": datetime.fromtimestamp(j["sent_at"], ZoneInfo("America/Chicago")).strftime("%Y-%m-%d %H:%M:%S"),
                       "State": j["state"], "Order": j.get("order_id"), "Fill price": j.get("fill_price"),
                       "Signal price": j.get("signal_entry"), "Slippage (pts, + adverse)": j.get("slippage_points"),
                       "Requested contracts": j.get("requested_quantity", j["quantity"]),
                       "Initial stop ticks": j.get("stop_ticks"),
                       "Stop verified": j.get("protected", False),
                       "Broker reason": j.get("error_message") or (f"Rejected / code {j.get('error_code')}" if j["state"] == "Rejected" else "")} for j in jobs]),
                     hide_index=True, width="stretch", height=min(260, 35 * len(jobs) + 38))
