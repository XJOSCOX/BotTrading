"""Research views with explicit data provenance and non-pooled results."""
from dataclasses import replace
from datetime import timedelta
import json

import pandas as pd
import streamlit as st

from goxtrade.market.instruments import instrument
from goxtrade.research.backtest import SimulationConfig, run_backtest, chronological_splits
from goxtrade.research.datasets import csv_minutes
from goxtrade.research.result_store import save_run
from goxtrade.strategies.strategy_catalog import STRATEGIES


def render_result(result, key):
    summary = result["summary"]
    for column, name in zip(st.columns(5), ("trades", "net", "win_rate", "profit_factor", "max_drawdown")):
        value = summary[name]
        column.metric(name.replace("_", " ").title(), "--" if value is None else f"{value:,.2f}" if isinstance(value, float) else value)
    st.caption(f"Historical simulation | {result['contract_id']} | {result['start']} to {result['end']} | {result['provenance']}")
    st.caption(f"Dataset {result['dataset_hash'][:16]} | Costs {result['simulation']} | Open at end: {result['open_at_end']} | Ambiguous: {result['ambiguous_trades']}")
    if result["simulation"].get("commission_per_side") == 0:
        st.warning("Zero-cost sensitivity scenario" if result["simulation"].get("zero_cost_sensitivity") else "Legacy result: zero fees were not explicitly acknowledged; fee-inclusive performance is unverified.")
    if result.get("accounting"):
        st.caption("Accounting: "+str(result["accounting"]))
    if result.get("monthly_returns"):
        with st.expander("Monthly closed-trade returns (CT)"):
            st.dataframe(pd.DataFrame([dict(month=month, **value) for month, value in result["monthly_returns"].items()]), hide_index=True, width="stretch")
    with st.expander("Statistics & session breakdown"):
        st.dataframe(pd.DataFrame([summary]), hide_index=True, width="stretch")
        for group, values in result["breakdown"].items():
            st.markdown("**"+group.replace("_", " ").title()+"**")
            st.dataframe(pd.DataFrame([dict(group=name, **row) for name, row in values.items()]), hide_index=True, width="stretch")
    st.dataframe(pd.DataFrame(result["trades"]), hide_index=True, width="stretch")
    with st.expander("Assumptions & decisions"):
        st.write(result["limitations"])
        st.json(result["decisions"])
    st.download_button("Download research result", json.dumps(result, default=str, indent=2),
                       file_name="strategy_backtest.json", mime="application/json", key=key+"_download", icon=":material/download:")


def render_research(config):
    from goxtrade.data.strategy_history import load_strategy_minutes
    from goxtrade.execution.contracts import contract_for_symbol
    a, b, c = st.columns(3)
    symbol = a.selectbox("Research instrument", ("MNQ", "MES", "MYM", "NQ", "ES", "YM"), key="research_instrument")
    strategy = b.selectbox("Research strategy", STRATEGIES, index=len(STRATEGIES)-1, key="research_strategy")
    source = c.selectbox("Historical source", ("Upload actual OHLCV", "Saved contract history"), key="research_source")
    default_contract = contract_for_symbol(symbol+"=F") or ""
    contract = st.text_input("Actual contract ID", value=default_contract, key="research_contract")
    st.caption("Single contract only. Split runs at rollovers. CSV: timezone-aware time, open, high, low, close, actual traded volume.")
    uploaded = st.file_uploader("Minute OHLCV CSV", type="csv", key="research_minutes") if source == "Upload actual OHLCV" else None
    ticks_file = st.file_uploader("Intrabar trades CSV (required for REALTIME / ANTICIPATORY)", type="csv", key="research_ticks")
    a, b, c = st.columns(3)
    today = pd.Timestamp.now(tz="America/Chicago").date()
    begin = a.date_input("From (CT)", value=today-timedelta(days=7), key="research_start")
    end = b.date_input("Through (CT)", value=today, key="research_end")
    quantity = c.number_input("Contracts", 1, 4, 1, key="research_qty")
    a, b, c = st.columns(3)
    starting = a.number_input("Starting balance ($)", min_value=0., value=50000., key="research_balance")
    commission = b.number_input("Commission / contract / side ($)", min_value=0., value=None, step=.01, key="research_fee")
    slippage = c.number_input("Slippage / fill (ticks)", min_value=0, value=1, key="research_slip")
    zero_cost = st.checkbox("Zero-cost sensitivity scenario (explicitly ignore commission)", key="research_zero_cost")
    a, b = st.columns(2)
    max_risk = a.number_input("Research maximum initial risk ($, optional)", min_value=.01, value=None, key="research_max_risk")
    min_rr = b.number_input("Minimum effective RR after slippage", min_value=0., value=0., key="research_min_rr")
    a, b = st.columns(2)
    folds = a.number_input("Chronological walk-forward folds (0 = single run)", 0, 10, 0, key="research_folds")
    fraction = b.slider("Initial training fraction", .1, .9, .7, .05, key="research_training")
    baseline = st.checkbox("Compare with optional filters disabled", key="research_raw")
    spec = instrument(symbol)
    st.caption(f"{symbol}: tick {spec.tick_size:g}, ${spec.tick_value:g}/tick, ${spec.point_value:g}/point. VWAP uses saved Parameters: {config.signal_minutes}m / {config.entry_mode} / {config.stop_method} / RR {config.reward_risk:g} / {config.management_method}.")
    if strategy != "VWAP EMA Cross":
        st.caption("Legacy research preserves its 15-minute signal definition and current buffered-stop policy; VWAP-specific parameters do not apply.")
    if st.button("Run historical research", icon=":material/science:", key="run_strategy_research"):
        try:
            if begin > end:
                raise ValueError("Start must not be after end")
            if source == "Upload actual OHLCV":
                if uploaded is None:
                    raise ValueError("Upload actual historical data first")
                minutes = csv_minutes(uploaded.getvalue())
                minutes.attrs["provenance"] = "User-supplied historical CSV: "+uploaded.name
            else:
                minutes = load_strategy_minutes(symbol+"=F", contract, pd.Timestamp.now(tz="UTC"),
                                                hours=max(72, (today-begin).days*24+48), refresh=False)
                minutes = minutes.loc[minutes["complete"].eq(True)]
            lower = pd.Timestamp(begin, tz="America/Chicago").tz_convert("UTC")
            upper = pd.Timestamp(end+timedelta(days=1), tz="America/Chicago").tz_convert("UTC")
            minutes = minutes.loc[(minutes["time"] >= lower-pd.Timedelta(hours=72)) & (minutes["time"] < upper)]
            ticks = pd.read_csv(ticks_file) if ticks_file is not None else None
            if ticks is not None:
                stamps = pd.to_datetime(ticks["time"], utc=True)
                ticks = ticks.loc[(stamps >= lower) & (stamps < upper)]
            sim = SimulationConfig(quantity=quantity, starting_balance=starting, commission_per_side=0. if zero_cost else commission,
                                   zero_cost_sensitivity=zero_cost, slippage_ticks=slippage, cooldown_minutes=config.cooldown_minutes,
                                   max_initial_risk_usd=max_risk, minimum_effective_rr=min_rr).validate()
            args = dict(symbol=symbol, contract_id=contract, strategy=strategy,
                        strategy_config=config.to_dict() if strategy == "VWAP EMA Cross" else None, simulation=sim, trade_start=lower)
            if folds and (ticks is not None or (strategy == "VWAP EMA Cross" and config.entry_mode != "CONFIRMED")):
                raise ValueError("Walk-forward splitting currently supports completed-minute CONFIRMED runs only")
            with st.spinner("Replaying supplied observations"):
                result = run_backtest(minutes, ticks=ticks, **args)
                record_id = save_run(args, result)
                output = [(f"Run #{record_id}", result)]
                if baseline and strategy == "VWAP EMA Cross":
                    raw = replace(config, **{name: False for name in ("separation_enabled", "ema_slope_enabled", "vwap_slope_enabled", "volume_enabled", "volatility_enabled", "session_filter_enabled", "distance_enabled")})
                    raw_args = {**args, "strategy_config": raw.to_dict()}
                    raw_result = run_backtest(minutes, ticks=ticks, **raw_args)
                    raw_id = save_run(raw_args, raw_result)
                    output.append((f"Filters disabled / run #{raw_id}", raw_result))
                if folds:
                    for fold in chronological_splits(minutes, folds=folds, training_fraction=fraction, **args):
                        for kind in ("in_sample", "out_of_sample"):
                            child = fold[kind]
                            child_id = save_run(dict(**args, split_at=fold["split_at"], fold=fold["fold"], partition=kind), child)
                            output.append((f"Fold {fold['fold']} / {kind} / run #{child_id}", child))
            st.session_state["strategy_research_output"] = output
        except (ValueError, KeyError, TypeError) as error:
            st.error(str(error))
    for index, (label, result) in enumerate(st.session_state.get("strategy_research_output", [])):
        st.markdown("**"+label+"**")
        render_result(result, f"research_result_{index}")


def render_comparison(prefix="dashboard"):
    from goxtrade.research.performance import TYPES, population, comparison
    kind = st.selectbox("Results population", TYPES, key=prefix+"_population", format_func=lambda value: value.replace("_", " ").title())
    try:
        rows = population(kind)
    except (ValueError, KeyError, TypeError) as error:
        st.error(f"Results unavailable: {error}")
        return
    st.caption("Sources remain separate. Historical rows retain their run, dataset and date context. Broker rows use matched actual fills and reported costs only.")
    if not rows:
        st.info("No completed trades in this population.")
        return
    filters = {}
    for column, field in zip(st.columns(4), ("symbol", "strategy", "session", "timeframe")):
        choices = sorted({row.get(field) for row in rows if row.get(field) is not None}, key=str)
        choice = column.selectbox(field.title(), [None, *choices], format_func=lambda value: "All" if value is None else str(value), key=prefix+"_filter_"+field)
        filters[field] = choice
    a, b = st.columns(2)
    oldest = min(pd.Timestamp(row["exit_time"]).tz_convert("America/Chicago").date() for row in rows)
    newest = max(pd.Timestamp(row["exit_time"]).tz_convert("America/Chicago").date() for row in rows)
    start = a.date_input("Closed from (CT)", oldest, key=prefix+"_closed_from")
    end = b.date_input("Closed through (CT)", newest, key=prefix+"_closed_to")
    filters.update(start=pd.Timestamp(start, tz="America/Chicago"), end=pd.Timestamp(end+timedelta(days=1), tz="America/Chicago"))
    summary = comparison(rows, **filters)
    st.dataframe(pd.DataFrame(summary), hide_index=True, width="stretch")
    new = [row for row in summary if row["strategy"] == "VWAP EMA Cross"]
    if new:
        st.markdown("**VWAP EMA Cross / independent results**")
        st.dataframe(pd.DataFrame(new), hide_index=True, width="stretch")
    st.download_button("Download comparison", pd.DataFrame(summary).to_csv(index=False), "strategy_comparison.csv", "text/csv", key=prefix+"_comparison_download", icon=":material/download:")
