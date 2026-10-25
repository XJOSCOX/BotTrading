"""Legacy UI for the same shared manager service and research-only settings."""
from dataclasses import asdict
from io import StringIO

import pandas as pd
import streamlit as st

from goxtrade.execution import manager_service
from goxtrade.strategies.strategy_catalog import SPECS


def render(profile="practice"):
    st.subheader("Strategy Manager")
    st.caption("Shared monitoring and research configuration / account-specific shadow view / broker cutover disabled")
    view = manager_service.overview(profile)
    names = {spec.id: spec.name for spec in SPECS}
    overview, settings, research, paper, journal = st.tabs(["Overview", "Research policy", "Portfolio backtest", "Paper portfolio", "Decision journal"])
    with overview:
        st.write(view["session"]["reason"])
        st.caption("Broker snapshot: "+("fresh local reconciliation" if view["broker_fresh"] else "unavailable / stale"))
        decisions = {row["candidate_id"]: row for row in view["decisions"]}
        st.dataframe([{"Strategy": row["strategy_name"], "Symbol": row["symbol"], "Direction": row["direction"],
                       "Timeframe": row["timeframe"], "Entry mode": row["classification"], "Confirmation": row["confirmed_at"],
                       "Price": row["price"], "Stop": row["stop"], "Target": row["target"],
                       "Estimated risk": decisions[row["candidate_id"]]["planned_risk"], "Eligibility": decisions[row["candidate_id"]]["eligibility"],
                       "Priority": view["policy"]["priority"].index(row["strategy_id"])+1 if row["strategy_id"] in view["policy"]["priority"] else None,
                       "Decision": decisions[row["candidate_id"]]["execution_status"], "Reason": "; ".join(decisions[row["candidate_id"]]["reasons"])} for row in view["candidates"]], hide_index=True, width="stretch")
        st.dataframe(view["decisions"], hide_index=True, width="stretch")
        st.dataframe(view["adapter_rejections"], hide_index=True, width="stretch")
        if st.button("Record manager shadow decisions", key="manager_shadow"):
            manager_service.shadow(profile, persist=True)
            st.success("Shadow decisions recorded. No orders or account permissions changed.")
    with settings:
        draft = view["policy"]
        with st.form("manager_research_policy"):
            values = dict(draft)
            values["mode"] = st.selectbox("Arbitration policy", ["conservative", "first_confirmed", "configured_priority", "evidence_research"], index=["conservative", "first_confirmed", "configured_priority", "evidence_research"].index(draft["mode"]))
            values["monitoring"] = st.multiselect("Manager monitoring", list(names), default=draft["monitoring"], format_func=names.get)
            values["participating"] = st.multiselect("Research participation", list(names), default=draft["participating"], format_func=names.get)
            values["priority"] = st.multiselect("Configured priority / first has highest priority", list(names), default=draft["priority"], format_func=names.get)
            values["symbols"] = st.multiselect("Research instruments", ["MNQ", "MES", "MYM", "NQ", "ES", "YM"], default=draft["symbols"])
            columns = st.columns(3)
            numeric = [key for key, value in draft.items() if type(value) in (int, float)]
            for index, key in enumerate(numeric):
                values[key] = columns[index % 3].number_input(key.replace("_", " "), min_value=0 if type(draft[key]) is int else 0., value=draft[key], key="manager_"+key)
            if draft["commission_per_side"] is None:
                values["commission_per_side"] = st.number_input("Commission per contract / side", min_value=0., value=0., key="manager_explicit_fee")
            values["zero_cost_acknowledged"] = st.checkbox("Explicit zero-cost sensitivity acknowledgement", value=draft["zero_cost_acknowledged"])
            values["paper_enabled"] = st.checkbox("Enable separate portfolio paper entries", value=draft["paper_enabled"])
            budgets = dict(draft["strategy_budgets"])
            values["strategy_budgets"] = []
            for spec in SPECS:
                amount = st.number_input(spec.name+" paper risk budget / zero uses shared budget", min_value=0., value=float(budgets.get(spec.id, 0)), key="manager_budget_"+spec.id)
                if amount:
                    values["strategy_budgets"].append((spec.id, amount))
            if st.form_submit_button("Save manager research policy"):
                try:
                    manager_service.save_policy(values)
                    st.success("Research settings saved. Broker settings remain unchanged.")
                except ValueError as error:
                    st.error(str(error))
    with research:
        with st.form("manager_portfolio_research"):
            datasets = []
            chosen = st.multiselect("Historical instruments", ["MNQ", "MES", "MYM", "NQ", "ES", "YM"], default=["MNQ"], max_selections=3)
            for symbol in chosen:
                contract = st.text_input(symbol+" actual historical contract", key="manager_contract_"+symbol)
                file = st.file_uploader(symbol+" finalized minute CSV", type=["csv"], key="manager_file_"+symbol)
                if file:
                    datasets.append((symbol, contract, pd.read_csv(file)))
            walk = st.checkbox("Chronological out-of-sample folds / fixed policy")
            compare = st.checkbox("Compare individual strategies and arbitration modes")
            if st.form_submit_button("Run portfolio backtest"):
                from goxtrade.research.portfolio_backtest import run_portfolio_backtest, compare_portfolios, walk_forward
                try:
                    policy, configurations = manager_service.policy(), manager_service.shared_strategy_configs()
                    result = run_portfolio_backtest(datasets, policy, configurations)
                    if compare:
                        result["comparisons"] = {key: value["summary"] for key, value in compare_portfolios(datasets, policy, configurations).items()}
                    if walk:
                        result["walk_forward"] = walk_forward(datasets, policy, configurations)
                    manager_service.save_simulation(result)
                    st.success("Portfolio research saved separately from broker results.")
                except ValueError as error:
                    st.error(str(error))
        for run in view["runs"]:
            if run["kind"] == "portfolio_backtest":
                with st.expander("Portfolio run "+run["id"][:12]):
                    st.json(run["record"]["summary"])
                    st.dataframe(run["record"]["state"]["trades"], hide_index=True, width="stretch")
                    st.dataframe(run["record"]["state"]["decisions"], hide_index=True, width="stretch")
    with paper:
        st.caption("Independent portfolio paper history, not strategy-level paper or broker fills")
        if st.button("Start portfolio paper worker", disabled=not view["policy"]["paper_enabled"]):
            from goxtrade.runtime.manager_paper_worker import start
            st.info(start())
        if st.button("Evaluate current portfolio paper observations"):
            st.json(manager_service.paper_once())
        for run in view["runs"]:
            if run["kind"] == "portfolio_forward_paper":
                st.json(run["record"]["summary"])
                st.dataframe(run["record"]["state"]["positions"], hide_index=True, width="stretch")
    with journal:
        st.dataframe(view["journal"], hide_index=True, width="stretch")
        st.dataframe(view["reservations"], hide_index=True, width="stretch")
