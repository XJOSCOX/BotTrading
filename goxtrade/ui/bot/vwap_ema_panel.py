"""Additive strategy workspace; changing parameters never arms an account."""
import pandas as pd
import streamlit as st

from goxtrade.strategies.vwap_ema_config import MODES, SOURCES, VwapEmaConfig
from goxtrade.strategies.strategy_settings import read_vwap_ema_config, save_vwap_ema_config


OPTIONS = dict(entry_mode=MODES, signal_minutes=(1, 3, 5, 10, 15, 30, 60),
               ema_source=SOURCES, vwap_source=SOURCES, anchor=("futures", "rth", "custom"),
               stop_method=("atr", "swing", "fixed", "buffered"),
               management_method=("fixed", "trailing", "breakeven", "adaptive"),
               management_minutes=(1, 3, 5, 10, 15, 30))
LABELS = dict(practice_enabled="Allow VWAP EMA Cross in Practice", paper_enabled="Enable forward-paper simulation",
              monitor_enabled="Monitor VWAP EMA Cross", signal_minutes="Signal candles (minutes)",
              custom_anchor="Custom anchor (HH:MM)", timezone="Session timezone (IANA)",
              paper_commission_per_side="Paper commission per contract / side ($)",
              paper_slippage_ticks="Paper slippage per fill (ticks)", notify_wait="Notify when waiting reason changes")
GROUPS = {
    "Indicators & timing": ("entry_mode", "signal_minutes", "ema_length", "ema_source", "vwap_source", "anchor",
                            "custom_anchor", "timezone", "warmup_bars", "entry_window_seconds", "max_data_age_seconds", "cooldown_minutes"),
    "Entry filters": ("separation_enabled", "separation_ticks", "separation_atr", "ema_slope_enabled", "vwap_slope_enabled",
                      "volume_enabled", "volume_lookback", "volume_multiplier", "volatility_enabled", "atr_min_ticks", "atr_max_ticks",
                      "session_filter_enabled", "sessions", "custom_windows", "distance_enabled", "max_distance_ticks", "max_distance_atr"),
    "Anticipation": ("anticipation_distance_ticks", "anticipation_observations", "anticipation_min_slope_ticks"),
    "Stops & management": ("stop_method", "atr_length", "atr_multiple", "swing_bars", "fixed_stop_ticks", "reward_risk",
                           "management_method", "management_minutes", "trail_start_r", "trail_ticks", "breakeven_r"),
    "Paper & notifications": ("paper_enabled", "paper_quantity", "paper_commission_per_side", "paper_slippage_ticks", "notify_signals", "notify_wait"),
}


def input_field(name, value):
    label = LABELS.get(name, name.replace("_", " ").capitalize())
    key = "vwap_setting_"+name
    if name in OPTIONS:
        choices = OPTIONS[name]
        return st.selectbox(label, choices, index=list(choices).index(value), key=key)
    if isinstance(value, bool):
        return st.checkbox(label, value=value, key=key)
    if isinstance(value, tuple):
        if name in ("enabled_symbols", "sessions"):
            choices = ("NQ=F", "ES=F", "YM=F") if name == "enabled_symbols" else ("Regular", "Extended", "Overnight", "First hour", "Custom")
            return st.multiselect(label, list(dict.fromkeys((*choices, *value))), default=list(value), key=key)
        return tuple(part.strip() for part in st.text_input(label, ", ".join(value), key=key).split(",") if part.strip())
    if isinstance(value, (int, float)):
        return st.number_input(label, value=value, min_value=0 if isinstance(value, int) else 0., key=key)
    return st.text_input(label, value, key=key)


def configuration(config):
    with st.form("vwap_ema_parameters"):
        values = config.to_dict()
        a, b = st.columns(2)
        with a:
            values["monitor_enabled"] = input_field("monitor_enabled", config.monitor_enabled)
            values["enabled_symbols"] = input_field("enabled_symbols", config.enabled_symbols)
        with b:
            values["practice_enabled"] = input_field("practice_enabled", config.practice_enabled)
            st.caption("Leader: prohibited. Practice also requires account arming and strategy selection in Controls & review.")
        for title, names in GROUPS.items():
            with st.expander(title, expanded=title == "Indicators & timing"):
                columns = st.columns(3)
                for index, name in enumerate(names):
                    with columns[index % 3]:
                        values[name] = input_field(name, getattr(config, name))
        if st.form_submit_button("Save VWAP settings", icon=":material/save:"):
            try:
                save_vwap_ema_config(VwapEmaConfig.from_dict(values))
            except (ValueError, TypeError) as error:
                st.error(str(error))
            else:
                st.success("Saved for new setups. Existing position settings are unchanged; no account was armed.")


@st.fragment(run_every="2s")
def live_detail(config):
    from goxtrade.bot.bot_monitor import read_status
    from goxtrade.bot.strategy_events import recent_events
    from goxtrade.data.strategy_history import load_strategy_minutes, latest_trade
    from goxtrade.execution.contracts import contract_for_symbol
    from goxtrade.strategies.vwap_ema_indicators import indicator_frame
    from goxtrade.ui.bot.strategy_chart import render_strategy_chart
    symbol = st.selectbox("Chart symbol", config.enabled_symbols, key="vwap_chart_symbol")
    result = read_status().get((symbol, "VWAP EMA Cross"), {})
    snapshot = result.get("indicator_snapshot", {})
    signal = result.get("signal", snapshot)
    contract = contract_for_symbol(symbol)
    now = pd.Timestamp.now(tz="UTC")
    tick = latest_trade(symbol, contract)
    stamp = pd.Timestamp(tick["event_time"]) if tick else None
    age = (now-stamp).total_seconds() if stamp is not None else None
    values = [("State", snapshot.get("raw_signal", "WAIT")), ("Mode", config.entry_mode),
              (f"EMA {config.ema_length}", snapshot.get("ema")), ("Session VWAP", snapshot.get("vwap")),
              ("EMA - VWAP", snapshot.get("indicator_distance")), ("Trade age", f"{age:.1f}s" if age is not None else "No trades")]
    for column, (label, value) in zip(st.columns(6), values):
        column.metric(label, f"{value:,.2f}" if isinstance(value, float) else str(value) if value is not None else "--")
    st.caption(f"{'Monitoring' if config.monitor_enabled else 'Disabled'} | {config.signal_minutes}m | {contract or 'No contract'} | Updated {result.get('updated_at', '--')}")
    st.info(snapshot.get("reason", "Waiting for the monitor worker and complete session data."))
    st.caption(f"Latest cross: {snapshot.get('latest_crossover_direction') or '--'} | Last cross time: {snapshot.get('last_signal_timestamp') or '--'}")
    if result.get("forward_paper"):
        st.caption("Forward paper: "+result["forward_paper"].get("message", "--"))
    try:
        minutes = load_strategy_minutes(symbol, contract, now, refresh=False)
        candles = indicator_frame(minutes, now, config, tick["id"] if tick else None)
        if not candles.empty:
            render_strategy_chart(candles, symbol, config, recent_events(symbol), signal)
    except (ValueError, TypeError, KeyError) as error:
        st.warning(f"Chart data unavailable: {error}")


def render():
    st.subheader("VWAP EMA Cross")
    st.caption("Monitoring / Practice opt-in / Leader prohibited")
    try:
        config = read_vwap_ema_config()
    except (ValueError, TypeError) as error:
        st.error(f"Invalid strategy configuration: {error}")
        return
    live, settings, research, results = st.tabs(["Signal & chart", "Parameters", "Backtest", "Comparison"])
    with live:
        live_detail(config)
    with settings:
        configuration(config)
    with research:
        from goxtrade.ui.bot.strategy_research import render_research
        render_research(config)
    with results:
        from goxtrade.ui.bot.strategy_research import render_comparison
        render_comparison("bot")
