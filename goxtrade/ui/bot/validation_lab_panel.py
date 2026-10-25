"""Legacy access to the same research-only dataset/job/result service."""
import json
from datetime import datetime,timedelta,timezone
import streamlit as st
from goxtrade.research import lab_service,lab_jobs,lab_reports
from goxtrade.data import lab_store as store


def render():
    st.subheader("Strategy Validation Lab")
    view=lab_service.overview()
    dataset_tab,test_tab,results_tab,jobs_tab=st.tabs(["Datasets","Backtesting","Results","Jobs"])
    with dataset_tab:
        with st.form("lab_dataset"):
            symbol=st.selectbox("Research instrument",["MNQ","MES","MYM","NQ","ES","YM"])
            contract=st.text_input("Actual contract ID")
            expiration=st.text_input("Actual contract expiration / YYYY-MM-DD")
            period=st.selectbox("Historical period",[7,30,90,180])
            end=st.text_input("End exclusive / UTC",datetime.now(timezone.utc).replace(second=0,microsecond=0).isoformat())
            start=st.text_input("Start / UTC",(datetime.now(timezone.utc)-timedelta(days=period)).replace(second=0,microsecond=0).isoformat())
            reviewed=st.checkbox("I reviewed exchange sessions and holidays for this interval")
            note=st.text_input("Calendar review reference")
            file=st.file_uploader("Actual minute OHLCV CSV",type="csv")
            source=st.text_input("Import source / volume provenance")
            fetch=st.form_submit_button("Retrieve historical bars")
            saved=st.form_submit_button("Use existing saved history")
            imported=st.form_submit_button("Import CSV")
            if fetch or saved or imported:
                try:
                    metadata=dict(symbol=symbol,contract_id=contract,expiration=expiration,start=start,end=end,calendar_reviewed=reviewed,calendar_note=note)
                    if imported:
                        if not file:raise ValueError("Choose an actual CSV")
                        lab_service.import_csv({**metadata,"csv":file.getvalue().decode("utf-8-sig"),"source":source,"volume_provenance":source})
                    elif saved:lab_service.import_saved(metadata)
                    else:lab_service.history(metadata)
                    st.success("Research request saved; no account settings changed")
                except (ValueError,TypeError) as error:st.error(str(error))
        for dataset in view["datasets"]:
            st.write(dataset["symbol"],dataset["contract_id"],dataset["quality"]["status"])
            st.json(dataset["quality"],expanded=False)
            st.download_button("Export "+dataset["id"][:8],"".join(lab_reports.export_dataset(dataset["id"])),file_name="historical-minutes.csv",mime="text/csv")
    with test_tab:
        available={d["id"]:d for d in view["datasets"] if d["quality"]["candles"] and d["quality"]["status"] in ("complete","partial")}
        with st.form("lab_backtest"):
            datasets=st.multiselect("Complete reviewed datasets",list(available),format_func=lambda key:available[key]["symbol"]+" / "+available[key]["contract_id"])
            strategies=st.multiselect("Research strategies",[s["id"] for s in view["strategies"]],default=["crt","reversal"])
            start=st.text_input("Test start / timezone-aware")
            end=st.text_input("Test end exclusive / timezone-aware")
            commission=st.number_input("Commission / contract / side",min_value=0.,value=.5)
            slippage=st.number_input("Adverse slippage / ticks",min_value=0,max_value=100,value=1)
            quantity=st.number_input("Maximum contracts",1,4,1)
            risk=st.number_input("Per-trade research risk",min_value=1.,value=75.)
            mode=st.selectbox("Arbitration",["conservative","first_confirmed","configured_priority"])
            sessions=st.selectbox("Research session",["all","Regular","Overnight"])
            balance=st.number_input("Initial simulated balance",min_value=1.,value=50000.)
            configs=st.text_area("Frozen strategy configurations",json.dumps(view["configurations"],indent=2))
            exits=st.checkbox("Compare ten exit policies")
            portfolio=st.checkbox("Compare portfolio arbitration and risk")
            folds=st.checkbox("Chronological unseen windows")
            sensitivity=st.checkbox("Commission and slippage sensitivity")
            if st.form_submit_button("Run historical validation"):
                try:
                    lab_service.validation(dict(datasets=datasets,strategies=strategies,start=start,end=end,initial_balance=balance,session=sessions,
                        execution=dict(commission_per_side=commission,zero_cost_acknowledged=commission==0,slippage_ticks=slippage,requested_quantity=quantity,max_trade_risk=risk,mode=mode),
                        configurations={k:v for k,v in json.loads(configs).items() if k in strategies},compare_exits=exits,compare_portfolios=portfolio,walk_forward=folds,sensitivity=sensitivity))
                    st.success("Research job queued")
                except (ValueError,TypeError) as error:st.error(str(error))
    with results_tab:
        st.dataframe(view["runs"],hide_index=True,width="stretch")
        if view["runs"]:
            identifier=st.selectbox("Saved simulated run",[r["id"] for r in view["runs"]])
            run=store.get("lab_runs",identifier)
            st.warning(run["result"]["lab"]["statistical_warning"])
            st.line_chart(run["result"]["lab"]["equity"])
            st.dataframe(run["result"]["state"]["trades"],hide_index=True,width="stretch")
            st.json(run["result"]["summary"],expanded=False)
            st.download_button("Research HTML report",lab_reports.html_report(run),file_name="validation-report.html",mime="text/html")
            st.download_button("Simulated trades CSV",lab_reports.trades_csv(run),file_name="simulated-trades.csv",mime="text/csv")
    with jobs_tab:
        for job in view["jobs"]:
            st.write(job["kind"],job["status"],job.get("message",job.get("phase","")))
            st.progress(job["progress"])
            if job["status"]!="complete":
                if st.button("Resume",key="resume_"+job["id"],disabled=not job["can_resume"]):lab_jobs.start(job["id"])
                if st.button("Cancel",key="cancel_"+job["id"]):lab_jobs.cancel(job["id"])
