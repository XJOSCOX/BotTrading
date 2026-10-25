"""Execution-only workspace. Strategy settings and account identities live separately."""
from html import escape
import streamlit as st
from goxtrade.ui.shell import page_header
from goxtrade.ui.execution import live_theme
from goxtrade.execution import practice_executor, leader_execution, practice_safety
from goxtrade.execution.projectx_client import credentials_present
from goxtrade.config import execution_identity


def render_live():
    live_theme.apply()
    with st.container(key="live_workspace"):
        page_header("Trading", "Execution", "Account-specific Run/Pause, protection and actual fills", "MICRO FUTURES")
        profile = st.selectbox("Execution account", ["practice", "leader"], format_func=str.title, key="execution_profile")
        target = execution_identity.TARGETS[profile]
        settings, runtime, jobs = (practice_executor.snapshot() if profile == "practice" else leader_execution.snapshot())
        name = escape(target["name"])
        st.html(f'<div class="gx-context"><strong>{profile.title()}</strong><span>{name}</span><span>Account {target["id"]}</span><span>{"Entries enabled" if settings.get("enabled") else "Entries paused"}</span></div>')
        if not credentials_present():
            st.info("Configure the API key on Connection before enabling execution.")
        left, right = st.columns([1, 2.1], gap="large")
        with left, st.container(key="live_controls"):
            st.subheader("Run controls")
            live_theme.status(settings.get("enabled"), _fresh(runtime), runtime.get("message", "Worker not started"))
            st.caption("Micro sizing")
            a, b, c = st.columns(3)
            for column, micro in zip((a, b, c), ("MNQ", "MES", "MYM")):
                column.metric(micro, str(settings.get("quantities", {}).get(micro, 2)) if micro != "MYM" or settings.get("enable_mym") else "Off")
            gate = practice_safety.snapshot(target["gate_id"])
            st.metric("Account loss / $500 lock", f"${gate.get('loss', 0):,.2f}" if gate else "Not verified")
            if gate.get("locked"):
                st.error("Account loss lock active. Explicit loss-reset acknowledgment is required.")
            pending = execution_identity.restart_required()
            if pending:
                st.warning("Restart required after account replacement. New entries are blocked.")
            with st.expander("Authorize new entries", expanded=not settings.get("enabled")):
                authorized = st.checkbox("I authorize trading on "+target["name"], key="authorize_"+profile)
                safeguards = st.checkbox("Auto OCO is enabled and this account has no manual trading. Copier configuration is verified.", key="oco_"+profile)
                reset = st.checkbox("I acknowledge the $500 loss and authorize a new loss baseline.", key="loss_ack_"+profile) if gate.get("locked") else False
                if st.button("Start "+profile.title(), icon=":material/play_arrow:", width="stretch", disabled=not credentials_present() or pending or not authorized or not safeguards or bool(settings.get("enabled"))):
                    try:
                        quantities = settings.get("quantities", dict(MNQ=2, MES=2, MYM=2))
                        if profile == "leader":
                            leader_execution.command("arm", confirmed_account=target["name"], copier_confirmed=True, acknowledge_loss=reset, quantities=quantities)
                        else:
                            practice_executor.arm(500, 500, True, quantities=quantities, acknowledge_loss=reset, enable_mym=settings.get("enable_mym", False))
                        st.success("Started for new signals only. Check worker status.")
                        st.rerun()
                    except Exception:
                        st.error("Start blocked by account preflight. Check account identity, feed, worker health and broker protection.")
            if st.button("Pause new entries", icon=":material/pause:", width="stretch", key="execution_pause"):
                try:
                    leader_execution.command("pause") if profile == "leader" else practice_executor.pause()
                    st.success("Entries paused. Existing positions remain monitored.")
                    st.rerun()
                except Exception:
                    st.error("Pause outcome unavailable. Verify the worker and broker before retrying.")
            if profile == "leader" and not _fresh(runtime):
                if st.button("Start Leader monitor", icon=":material/power_settings_new:", disabled=not credentials_present() or pending):
                    try:
                        leader_execution.start_worker()
                        st.success("Monitor requested with entries paused.")
                    except Exception:
                        st.error("Monitor could not start. Check Connection and worker logs.")
            with st.expander("Emergency close"):
                close = st.checkbox("Close bot-owned positions and pause entries", key="emergency_"+profile)
                if st.button("Request close", icon=":material/stop_circle:", disabled=not close or not credentials_present()):
                    try:
                        leader_execution.command("emergency", confirmed_account=target["name"]) if profile == "leader" else practice_executor.request_emergency_close(True)
                        st.warning("Close requested, not confirmed. Verify broker exposure.")
                    except Exception:
                        st.error("Close outcome unavailable. Check the broker immediately.")
            st.caption("Strategy settings, quantities and re-entry timing are managed in Control Center.")
        with right:
            if profile == "leader":
                from goxtrade.ui.execution.leader_page import activity
                activity()
            else:
                from goxtrade.ui.execution.practice_page import render_trade_history, render_order_attempts
                render_trade_history()
                render_order_attempts()
        st.html('<div class="gx-policy"><b>Protective orders required</b><span>Watch alerts are not fills</span><span>Only broker-matched trades count toward P&amp;L</span><span>Topstep manages follower copies</span></div>')


def _fresh(runtime):
    from datetime import datetime, timezone
    try:
        return 0 <= (datetime.now(timezone.utc)-datetime.fromisoformat(runtime["updated_at"])).total_seconds() < 45
    except (KeyError, TypeError, ValueError):
        return False
