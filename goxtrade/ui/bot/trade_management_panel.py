"""Same research exit policy in both profiles; broker orders are read-only."""
import pandas as pd
import streamlit as st

from goxtrade.execution import profit_service


def render(profile="practice"):
    st.subheader("Trade Management")
    view = profit_service.view(profile)
    st.warning("Software protection is not a broker order. Amendments/partial broker exits are blocked. Existing positions keep original policies.")
    positions, policy, review, research = st.tabs(["Positions", "Exit policy", "Giveback review", "Policy comparison"])
    with positions:
        st.caption("Broker positions / original management")
        st.dataframe(view["broker_positions"], hide_index=True, width="stretch")
        st.caption("Separate paper positions / software protection")
        st.dataframe([{**{key:row.get(key) for key in ("population","strategy","symbol","entry","remaining","current_price","initial_stop","stop","break_even_level","locked_stop","target","marked_unrealized_gross","peak_mark_gross","giveback_gross","current_r","max_r","protection_status")}, "policy":row["policy"]["mode"], "next_partial_r":next((target[0] for index,target in enumerate(row["policy"]["partial_targets"]) if index not in row["completed_partials"]), None)} for row in view["paper_positions"]], hide_index=True, width="stretch")
    with policy:
        draft = dict(view["policy"])
        choices = dict(mode=["baseline","fixed","breakeven","trailing","profit_lock","partial","hybrid"], target_method=["strategy","structural","rr","ticks","points"], trailing_method=["fixed_ticks","atr","structure","extreme","adaptive"], management_minutes=[5,10,15])
        with st.form("shared_profit_policy"):
            for key,value in draft.items():
                if key == "version":
                    continue
                if key == "partial_targets":
                    frame = st.data_editor(pd.DataFrame(value, columns=["R", "contracts"], dtype=float), num_rows="dynamic", hide_index=True, key="profit_ladder")
                    draft[key] = frame
                elif key in choices:
                    draft[key] = st.selectbox(key.replace("_"," "), choices[key], index=choices[key].index(value))
                elif type(value) is bool:
                    draft[key] = st.checkbox(key.replace("_"," "), value=value)
                else:
                    draft[key] = st.number_input(key.replace("_"," "), value=value, step=1 if type(value) is int else .1)
            if st.form_submit_button("Save research/paper exit policy"):
                try:
                    ladder = draft["partial_targets"].dropna(how="all")
                    if ladder.isna().any().any():
                        raise ValueError("Each partial target needs both R and whole contracts")
                    draft["partial_targets"] = [[float(row["R"]), int(row["contracts"]) if float(row["contracts"]).is_integer() else float(row["contracts"])] for row in ladder.to_dict("records")]
                    profit_service.save_policy(draft)
                    st.success("Saved for new opted-in paper positions. No broker settings changed.")
                except (ValueError, TypeError) as error:
                    st.error(str(error))
    with review:
        st.dataframe([dict(population=row["population"], strategy=row.get("strategy"), symbol=row.get("symbol"), **row["management_analytics"]) for row in view["paper_closed"]], hide_index=True, width="stretch")
    with research:
        from goxtrade.execution.manager_service import policy as execution_policy, shared_strategy_configs
        from goxtrade.research.exit_policy_comparison import compare_exits, chronological_exit_folds
        with st.form("profit_comparison"):
            symbol = st.selectbox("Research instrument", ["MNQ","MES","MYM"])
            contract = st.text_input("Actual historical contract")
            file = st.file_uploader("Finalized minute OHLCV", type=["csv"])
            folds = st.checkbox("Chronological out-of-sample folds")
            if st.form_submit_button("Compare ten exit policies") and file:
                try:
                    datasets = [(symbol,contract,pd.read_csv(file))]
                    result = compare_exits(datasets, execution_policy(), shared_strategy_configs())
                    if folds:
                        result["walk_forward"] = chronological_exit_folds(datasets, execution_policy(), shared_strategy_configs())
                    profit_service.save_comparison(result)
                    st.success("Saved research comparison; no broker calls.")
                except ValueError as error:
                    st.error(str(error))
        for run in view["comparisons"]:
            st.dataframe([dict(policy=name, **row["summary"]["metrics"], **{key:value for key,value in row["diagnostics"].items() if key != "groups"}) for name,row in run["result"]["policies"].items()], hide_index=True, width="stretch")
