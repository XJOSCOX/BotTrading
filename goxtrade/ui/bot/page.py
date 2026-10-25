"""Strategy monitoring, alerts, and review page."""
import streamlit as st

from goxtrade.bot import bot_monitor
from goxtrade.data.live_store import latest_prices
from goxtrade.market.market_session import market_session
from goxtrade.bot.signal_lifecycle import alert_history
from goxtrade.ui import shell
from goxtrade.ui.bot import bot_view


@st.fragment(run_every='1s')
def render_monitor_history(account_profile="practice"):
    import pandas as pd
    session = market_session()
    results = bot_monitor.read_status()
    prices = latest_prices(bot_monitor.SYMBOLS)
    now = pd.Timestamp.now(tz="UTC")
    healthy = all(
        pair in results and (now - pd.Timestamp(results[pair]["updated_at"])).total_seconds() < 30
        for pair in ((s, t) for s in bot_monitor.SYMBOLS for t in bot_monitor.STRATEGIES)
    )
    history = alert_history(10000)
    history = [row for row in history if row["symbol"] in bot_monitor.SYMBOLS and row["strategy"] in bot_monitor.STRATEGIES]
    active = bot_view.recent_alerts([row for row in history if row["status"] == "Active"])
    closed = bot_view.recent_alerts([row for row in history if row["status"] == "Closed"])
    from goxtrade.execution import practice_executor; from goxtrade.execution import practice_history; from goxtrade.execution import executed_results
    if account_profile == "leader":
        from goxtrade.execution import leader_execution
        execution = leader_execution.snapshot()
        fills = leader_execution.history()[1]
    else:
        execution = practice_executor.snapshot()
        fills = practice_history.snapshot()[1]
    jobs = execution[2]
    from goxtrade.execution import leader_execution
    other_profile = "leader" if account_profile == "practice" else "practice"
    other_jobs = (leader_execution.snapshot() if other_profile == "leader" else practice_executor.snapshot())[2]
    other_open = [j for j in other_jobs if j.get("state") in ("Open", "Closing")]
    if other_open:
        details = ", ".join(f"{j['quantity']} {j['symbol']} / alert #{j['alert_id']}" for j in other_open)
        st.warning(f"{other_profile.title()} has an open trade: {details}. Current view: {account_profile.title()}. Select {other_profile.title()} in Account view for its trade status and P&L.")
    matched = executed_results.results(jobs, fills)
    by_alert = {j["alert_id"]: j for j in jobs}
    from goxtrade.bot import bot_audit
    entry_decisions = bot_audit.entry_decisions([row["id"] for row in history], account_profile)
    active, closed = bot_view.prioritized_alerts(history, by_alert)
    bot_view.monitoring_summary(
        f"{'Monitoring' if healthy else 'Monitor offline / starting'} | {account_profile.title()} | NQ, ES, YM | All strategies | {session['name']} | {session['time']:%H:%M:%S} CT",
        closed, executed_results.summary(matched),
    )
    if not healthy:
        st.warning("Strategy monitoring is delayed or starting. New entries require fresh strategy results; check worker and feed health.")
    left, right = st.columns([1.25, 1.75], gap="medium")
    with left:
        st.subheader("Strategy watch")
        if account_profile == "practice":
            st.session_state["bot_enable_mym"] = practice_executor.snapshot()[0].get("enable_mym", False)
            st.toggle("Enable MYM trading", key="bot_enable_mym",
                      on_change=lambda: practice_executor.set_mym_enabled(st.session_state["bot_enable_mym"]),
                      help="Allows new MYM Practice entries when automation is running. Disabling does not stop management of an existing position.")
        else:
            st.caption("Leader execution: MNQ / MES / MYM." if execution[0].get("enable_mym") else "Leader execution: MNQ / MES. MYM watch only.")
        bot_view.strategy_matrix(bot_monitor.SYMBOLS, results, prices, healthy, session["is_open"], history, by_alert)
    with right:
        st.subheader("Alert history")
        st.caption(account_profile.title()+" execution: " + execution[1].get("message", "Worker unavailable"))
        st.markdown(f"**Active alerts ({len(active)})**")
        from goxtrade.market.trading_schedule import execution_schedule
        schedule = execution_schedule()
        st.caption("Entry cutoff 14:50 CT / Scheduled flatten 15:05 CT / Reopen 17:00 CT")
        if not schedule["allow_entry"]:
            st.warning(schedule["reason"])
        watch_ids = [row["id"] for row in active if row["id"] not in by_alert or by_alert[row["id"]].get("state") == "Rejected"]
        if st.button("Clear watch-only alerts",icon=":material/clear_all:",disabled=not watch_ids,key="clear_watch_alerts",
                     help="Clears watch signals across both account views, including signals whose trades have already closed. Open, pending or uncertain orders remain protected. Trade history is retained."):
            from goxtrade.bot.watch_alerts import clear_watch_alerts
            count = clear_watch_alerts(watch_ids)
            skipped = len(watch_ids)-count
            st.toast(f"Cleared {count} watch-only alerts." + (f" {skipped} could not be cleared; check open or pending orders in both accounts." if skipped else ""))
            st.rerun(scope="fragment")
        if not active:
            st.info("No active alerts. Monitoring for the next setup.")
        for row in active:
            bot_view.history_card(row, prices.get(row["symbol"]), session["is_open"], by_alert.get(row["id"]), matched.get(row["id"]), entry_decisions.get(row["id"], []))
        with st.expander(f"Past alerts ({len(closed)})", expanded=False):
            symbol_col, strategy_col = st.columns(2)
            symbol_filter = symbol_col.selectbox("Symbol", ["All", "NQ", "ES", "YM"], key="alert_symbol_filter")
            strategy_filter = strategy_col.selectbox("Strategy", ["All", *bot_monitor.STRATEGIES], key="alert_strategy_filter")
            filtered = [row for row in closed
                        if (symbol_filter == "All" or row["symbol"].replace("=F", "") == symbol_filter)
                        and (strategy_filter == "All" or row["strategy"] == strategy_filter)]
            if not filtered:
                st.caption("No past alerts." if not closed else "No past alerts match these filters.")
            pages = max(1, (len(filtered) + 11) // 12)
            page = st.selectbox("Page", range(1, pages + 1), key="alert_history_page") if pages > 1 else 1
            for row in filtered[(page - 1) * 12:page * 12]:
                bot_view.history_card(row, job=by_alert.get(row["id"]), result=matched.get(row["id"]), decisions=entry_decisions.get(row["id"], []))


def render_bot() -> None:
    bot_view.theme()
    shell.page_header("Trading", "Strategies", "Live setups, entry evidence and execution decisions")
    from goxtrade.ui.bot import bot_workspace
    from goxtrade.execution import leader_execution; from goxtrade.execution import practice_executor
    if "bot_account_view" not in st.session_state:
        leader_state = leader_execution.snapshot()
        leader_active = leader_state[0].get("enabled") or any(j.get("state") in ("Open", "Closing", "Submitted", "Unknown", "Intent") for j in leader_state[2])
        st.session_state["bot_account_view"] = "leader" if leader_active else "practice"
    with st.container(key="bot_header_controls"):
        account_column, _ = st.columns([1, 3])
        account_profile = account_column.selectbox("Account view",["practice","leader"],format_func=str.title,key="bot_account_view",help="Changes the displayed account only; does not start or switch execution.")
    monitor, manager, protection, operations, research, vwap, box, inbox = st.tabs(["Monitor", "Strategy Manager", "Trade Management", "Trade review", "Replay lab", "VWAP EMA Cross", "Previous Day Box", "Notifications"])
    with protection:
        from goxtrade.ui.bot.trade_management_panel import render as render_protection
        render_protection(account_profile)
    with manager:
        from goxtrade.ui.bot.strategy_manager_panel import render as render_manager
        render_manager(account_profile)
    with box:
        from goxtrade.ui.bot.previous_day_box_panel import render as render_box
        render_box()
    with vwap:
        from goxtrade.ui.bot.vwap_ema_panel import render as render_vwap
        render_vwap()
    with monitor:
        with st.container(key="bot_monitor"):
            render_monitor_history(account_profile)
    with operations:
        with st.container(key="bot_operations"):
            bot_workspace.theme()
            if account_profile == "leader":
                from goxtrade.ui.execution.leader_page import activity
                activity()
            else:
                bot_workspace.operations_status()
                bot_workspace.timeline()
    with research:
        with st.container(key="bot_research"):
            bot_workspace.replay()
    with inbox:
        bot_workspace.notifications(account_profile)
