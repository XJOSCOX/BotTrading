"""Legacy UI for the same isolated offline replay and read-only diagnostics."""
import json
import streamlit as st
from goxtrade.replay import replay_session as replay
from goxtrade.diagnostics import projectx_diagnostics as diagnostics


def render():
    replay_tab,diagnostic_tab=st.tabs(["Market Replay","ProjectX Diagnostics"])
    with replay_tab:
        view=replay.overview()
        st.caption("Offline research / isolated virtual account / no broker orders")
        if not view["datasets"]:st.info("Import genuine minute OHLCV in Strategy Validation Lab before creating a replay.")
        with st.form("offline_replay_create"):
            sources={d["id"]:d for d in view["datasets"]}
            selected=st.multiselect("Replay datasets",list(sources),format_func=lambda k:sources[k]["symbol"]+" / "+sources[k]["contract_id"])
            strategies=st.multiselect("Replay strategies",[s["id"] for s in view["strategies"]],default=["crt","reversal"])
            start=st.text_input("Replay start / UTC")
            end=st.text_input("Replay end exclusive / UTC")
            balance=st.number_input("Starting virtual balance",min_value=1.,value=50000.)
            fee=st.number_input("Replay commission per side",min_value=0.,value=.5)
            risk=st.number_input("Replay per-trade risk",min_value=1.,value=75.)
            config=st.text_area("Frozen replay policy/settings overrides / JSON","{}")
            if st.form_submit_button("Create offline replay"):
                try:
                    created=replay.create(dict(datasets=selected,strategies=strategies,start=start,end=end,initial_balance=balance,
                        execution=dict(commission_per_side=fee,zero_cost_acknowledged=fee==0,max_trade_risk=risk),**json.loads(config)))
                    st.session_state["offline_replay_id"]=created["id"]
                except (ValueError,TypeError) as error:st.error(str(error))
        identifiers=[r["id"] for r in replay.overview()["sessions"]]
        if identifiers:
            identifier=st.selectbox("Saved offline session",identifiers,key="offline_replay_id")
            controls=st.columns(6)
            for column,name in zip(controls,("play","pause","step","candle","stop","restart")):
                if column.button(name.title(),key="offline_"+name):
                    try:
                        updated=replay.action(identifier,dict(action=name))
                        if name=="restart":st.success("New session saved: "+updated["id"])
                    except ValueError as error:st.error(str(error))
            playback=st.selectbox("Playback speed",[1,5,10,30,60,"maximum"])
            if st.button("Apply replay speed"):replay.action(identifier,dict(action="speed",speed=playback))
            render_state(identifier)
    with diagnostic_tab:
        st.caption("Read-only diagnostics; authentication/history require an explicit button press")
        evidence=diagnostics.overview()
        st.json(evidence,expanded=False)
        if st.button("Test ProjectX authentication"):
            try:st.json(diagnostics.run(dict(action="authenticate")))
            except ValueError as error:st.error(str(error))
        with st.form("offline_history_probe"):
            symbol=st.selectbox("Diagnostic instrument",["MNQ","MES","MYM","NQ","ES","YM"])
            contract=st.text_input("Diagnostic contract")
            start=st.text_input("Probe start / UTC")
            end=st.text_input("Probe end / UTC")
            if st.form_submit_button("Test ProjectX history"):
                try:st.json(diagnostics.run(dict(action="history",symbol=symbol,contract_id=contract,start=start,end=end)))
                except ValueError as error:st.error(str(error))


@st.fragment(run_every=1)
def render_state(identifier):
    record=replay.detail(identifier)
    st.write(record["status"],record["clock"],record["next_index"])
    st.json(record["virtual_account"],expanded=False)
    for symbol in {d["exposure"]["symbol"] for d in record["positions"]}:st.write(symbol,replay.chart(identifier,symbol))
    st.dataframe(record["positions"],width="stretch")
    st.dataframe(record["decisions"],width="stretch")
    st.dataframe(record["trades"],width="stretch")
    st.dataframe(record["events"],width="stretch")
