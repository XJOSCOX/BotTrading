"""Configuration-only workspace. Saving never starts execution."""
import streamlit as st
from goxtrade.ui.shell import page_header
from goxtrade.bot import bot_controls
from goxtrade.execution import practice_executor, leader_execution
from goxtrade.strategies import strategy_settings
from goxtrade.strategies.strategy_catalog import SPECS


def render():
    page_header("Trading", "Control Center", "Strategy selection, trade sizing and re-entry policy", "CONFIGURATION")
    from goxtrade.config.execution_identity import restart_required
    if restart_required():
        st.warning("Restart the app after account replacement before editing execution policy.")
        return
    execution, timing, indicator, box = st.tabs(["Execution policy", "Intervals & sessions", "VWAP EMA parameters", "Previous Day Box"])
    with execution:
        profile = st.selectbox("Execution profile", ["practice", "leader"], format_func=str.title, key="control_profile")
        settings = (practice_executor.snapshot() if profile == "practice" else leader_execution.snapshot())[0]
        policy = bot_controls.read(profile)
        left, right = st.columns([1.7, 1], gap="large")
        with left, st.container(key="control_editor"):
            st.subheader("Entry configuration")
            with st.form("execution_policy_"+profile):
                choices = [spec.name for spec in SPECS if profile in spec.execution_profiles]
                strategies = st.multiselect("Enabled strategies", choices, default=[name for name in policy["strategies"] if name in choices])
                st.dataframe([{"Strategy": spec.name, "Monitoring / parameters": "Shared across Practice and Leader", "Account execution": "Selectable" if profile in spec.execution_profiles else "Restricted - separate authorization required"} for spec in SPECS], hide_index=True, width="stretch")
                mym = st.toggle("Allow MYM entries", value=settings.get("enable_mym") is True)
                columns = st.columns(3)
                quantities = {name: column.number_input(name+" contracts", 1, 4, int(settings.get("quantities", {}).get(name, 2)), key="controls_qty_"+profile+name)
                              for name, column in zip(("MNQ", "MES", "MYM"), columns)}
                cooldown = st.number_input("Re-enter after a confirmed close (minutes)", 1, 60, int(policy["cooldown_minutes"]), key="controls_cooldown_"+profile)
                mode = policy["entry_confirmation_mode"]
                if profile == "practice":
                    mode = st.selectbox("Legacy strategy entry confirmation", ["strict", "standard"],
                                        index=["strict", "standard"].index(mode),
                                        format_func=lambda value: "Strict (15m + 5m + 1m)" if value == "strict" else "Standard (15m + 5m)")
                if st.form_submit_button("Save execution policy", icon=":material/save:"):
                    try:
                        if profile == "leader":
                            leader_execution.command("configure", quantities=quantities, strategies=strategies, cooldown=cooldown, enable_mym=mym)
                        else:
                            bot_controls.save(["MNQ", "MES"]+(["MYM"] if mym else []), strategies, cooldown, profile="practice",
                                              entry_confirmation_mode=mode)
                            practice_executor.configure(quantities, mym)
                        st.success("Policy saved. Run/Pause state unchanged.")
                    except (ValueError, RuntimeError, OSError):
                        st.error("Unable to save policy. Check worker availability and execution status.")
        with right:
            st.subheader("Execution safeguards")
            st.metric("Account loss lock", "$500")
            st.metric("Maximum / symbol", "4 micro contracts")
            st.caption("Additional symbols: one contract. Overnight: one position, one contract, at least 15 minutes after close.")
            st.caption("Stops follow strategy structure. Open positions retain their frozen management rules.")
            st.warning("Same strategies and settings in both profiles. Each account retains independent opt-in, Start/Pause and loss locks.")
    with timing:
        left, right = st.columns([1.6, 1], gap="large")
        with left:
            st.subheader("Candle intervals")
            with st.form("shared_interval_settings"):
                st.selectbox("Legacy strategy signal candles", ["15 minutes"], disabled=True)
                orb = st.selectbox("Opening range (minutes)", [5, 15, 30], index=[5, 15, 30].index(strategy_settings.read_orb_minutes()))
                stop = st.selectbox("Stop & trailing candles (minutes)", [5, 10, 15], index=[5, 10, 15].index(strategy_settings.read_stop_minutes()))
                if st.form_submit_button("Save candle intervals", icon=":material/save:"):
                    strategy_settings.save_orb_minutes(orb)
                    strategy_settings.save_stop_minutes(stop)
                    st.success("Saved for new setups. Existing positions are unchanged.")
        with right:
            st.subheader("Session boundaries / CT")
            st.table([{"Boundary": "New entry cutoff", "Time": "14:50"}, {"Boundary": "Flatten request", "Time": "15:05"}, {"Boundary": "Trading reopens", "Time": "17:00"}])
            st.caption("Exchange holidays, maintenance, volatility and stale data may restrict entries further.")
        st.subheader("Strategy intervals")
        st.dataframe([{"Strategy": spec.name, "Signal candles": "Configurable / default 3 min" if spec.id == "vwap_ema_cross" else "15 min", "Leader": "Prohibited" if "leader" not in spec.execution_profiles else "Eligible", "Entry policy": "Indicator crossover" if spec.id == "vwap_ema_cross" else "Multi-timeframe confirmation"} for spec in SPECS], hide_index=True, width="stretch")
    with indicator:
        from goxtrade.ui.bot.vwap_ema_panel import configuration
        from goxtrade.strategies.strategy_settings import read_vwap_ema_config
        configuration(read_vwap_ema_config())
    with box:
        from goxtrade.ui.bot.previous_day_box_panel import render as render_box
        render_box()
