"""Legacy Streamlit access to the same box engine, settings and research results."""
import json
import pandas as pd
import streamlit as st

from goxtrade.strategies.strategy_settings import read_previous_day_box_config, save_previous_day_box_config


def render():
    from goxtrade.data.previous_box_view import view
    from goxtrade.ui.market.live_chart_component import _chart
    config = read_previous_day_box_config()
    st.subheader("Previous Day Box Reversal")
    st.caption("Completed 15-minute candles / America/Chicago / Independent account authorization / No account armed by saving")
    symbol = st.selectbox("Box instrument",["NQ=F","ES=F","YM=F","MNQ=F","MES=F","MYM=F"],key="box_symbol")
    parameters, monitoring, research = st.tabs(["Parameters","Box & confirmation","Historical research"])
    with parameters:
        with st.form("previous_day_box_parameters"):
            st.caption("All validated parameters are available below. Zone percentages are research settings, not proven optimal values.")
            text = st.text_area("Previous Day Box configuration (JSON)",json.dumps(config.to_dict(),indent=2),height=480)
            if st.form_submit_button("Save box settings"):
                try:
                    save_previous_day_box_config(json.loads(text))
                except (ValueError,TypeError) as error:
                    st.error(str(error))
                else:
                    st.success("Saved. Account arming and existing positions are unchanged.")
    with monitoring:
        data = view(symbol)
        signal,box = data["signal"],data["box"]
        st.info(signal["reason"])
        if box:
            st.caption(f"Reference session {box['session_id']} / {box['session_definition']} / {data['contract_id']}")
            columns = st.columns(3)
            for index,name in enumerate(("pdh","pdl","midpoint","range","buy_upper","sell_lower")):
                columns[index%3].metric(name.replace("_"," ").title(),f"{box[name]:,.2f}")
        st.write(dict(zone=signal.get("zone"),bias=signal.get("direction"),confirmation=signal.get("confirmed_at"),quote=data["quote_time"]))
        _chart(points=data["points"],markers=data["markers"],levels=data["levels"],box=box,symbol=symbol,height=720,
               timeframe="15min",range_label="48H",candle_label="15 min",key="previous_day_box_chart_"+symbol,default=None)
        st.dataframe(pd.DataFrame(data["events"]),hide_index=True,use_container_width=True)
    with research:
        from goxtrade.research.backtest import run_backtest, SimulationConfig
        from goxtrade.research.result_store import save_run
        upload = st.file_uploader("Actual contract minute OHLCV CSV",type="csv",key="box_csv")
        contract = st.text_input("Actual box research contract ID",key="box_contract")
        fee = st.number_input("Box commission / contract / side ($)",min_value=0.,value=0.,key="box_fee")
        zero = st.checkbox("Acknowledge zero-cost sensitivity scenario",key="box_zero")
        if st.button("Run box backtest",disabled=upload is None or not contract):
            try:
                result = run_backtest(pd.read_csv(upload),symbol,contract,"previous_day_box",config,SimulationConfig(commission_per_side=fee,zero_cost_sensitivity=zero))
                save_run(dict(strategy_id="previous_day_box",contract_id=contract),result)
                st.json(result)
            except (ValueError,TypeError) as error:
                st.error(str(error))
