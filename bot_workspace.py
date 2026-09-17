"""Practice operations and isolated research surfaces."""
import json
from contextlib import closing
from datetime import datetime, timezone
import pandas as pd
import streamlit as st
import bot_audit
import bot_controls
import practice_executor as executor
import practice_history
from bot_view import ct
from strategy_catalog import STRATEGIES


def theme():
    st.html('''<style>
    :is(.st-key-bot_operations,.st-key-bot_research) [data-baseweb="select"]>div,
    :is(.st-key-bot_operations,.st-key-bot_research) [data-baseweb="input"],
    :is(.st-key-bot_operations,.st-key-bot_research) [data-baseweb="base-input"],
    :is(.st-key-bot_operations,.st-key-bot_research) input {background:#22292c!important;color:#e5edef!important;}
    :is(.st-key-bot_operations,.st-key-bot_research) [data-testid="stNumberInputContainer"] button {background:#293337!important;color:#bddbd2!important;}
    :is(.st-key-bot_operations,.st-key-bot_research) [data-baseweb="tag"] {background:#304b43!important;color:#98e4c9!important;}
    :is(.st-key-bot_operations,.st-key-bot_research) [data-testid="stFormSubmitButton"] button {background:#283b34;color:#b8ead5;border:1px solid #567d6c;}
    :is(.st-key-bot_operations,.st-key-bot_research) h3 {font-size:17px!important;}
    :is(.st-key-bot_operations,.st-key-bot_research) [data-testid="stMetricValue"] {font-size:21px!important;}
    :is(.st-key-bot_operations,.st-key-bot_research) [data-testid="stForm"] {border:0;padding:0;}
    </style>''')


def table(frame, height=360):
    if frame.empty:
        st.caption("No records yet.")
        return
    markup = frame.to_html(index=False,escape=True,border=0,float_format=lambda value:f"{value:,.2f}",na_rep="--")
    st.html(f'''<style>
    .ops-table {{overflow:auto;border-block:1px solid #354246;font-size:12px;color:#d6e3e2;}}
    .ops-table table {{border-collapse:collapse;width:100%;}}
    .ops-table th {{position:sticky;top:0;background:#232c30;color:#a4babd;font-weight:500;font-size:11px;text-align:left!important;white-space:nowrap;}}
    .ops-table td,.ops-table th {{padding:10px 12px;border-bottom:1px solid #303c40;min-width:75px;max-width:360px;}}
    .ops-table td {{background:#171d20;overflow-wrap:anywhere;}}
    .ops-table tr:hover td {{background:#232f31;}}
    </style><div class="ops-table" style="max-height:{height}px">{markup}</div>''')


def controls():
    settings, runtime, _ = executor.snapshot()
    policy = bot_controls.read()
    st.subheader("Practice control center")
    st.caption(f"{executor.ACCOUNT_NAME} / Micro contracts only / $500 account loss lock")
    if runtime.get("version") not in ("operations-v1","accounts-v1"):
        st.warning("Operations worker update pending. New controls require the updated worker.")
    with st.form("bot_control_center"):
        a, b = st.columns(2)
        symbols = a.multiselect("Execution symbols", ["MNQ", "MES", "MYM"], default=[s for s in policy["symbols"] if s != "MYM" or settings.get("enable_mym")])
        strategies = b.multiselect("Execution strategies", STRATEGIES, default=policy["strategies"])
        columns = st.columns(3)
        quantities = {s:columns[i].number_input(s+" contracts",1,4,int(settings.get("quantities",{}).get(s,2))) for i,s in enumerate(("MNQ","MES","MYM"))}
        cooldown = st.number_input("Cooldown (minutes)",1,60,int(policy["cooldown_minutes"]))
        if st.form_submit_button("Save controls", icon=":material/save:"):
            bot_controls.save(symbols, strategies, cooldown)
            executor.configure(quantities, "MYM" in symbols)
            st.success("Saved for new entries. Existing positions remain managed.")
    a,b = st.columns(2)
    if a.button("Pause new entries",icon=":material/pause:",key="bot_pause_entries"):
        executor.pause()
        st.success("New entries paused. Exit management continues.")
    with b.expander("Start Practice"):
        confirmed = st.checkbox("Practice is isolated from copiers, uses Auto OCO, and has no manual trading.",key="bot_start_confirmation")
        if st.button("Start Practice",icon=":material/play_arrow:",disabled=not confirmed or bool(settings.get("enabled")),key="bot_start_execution"):
            try:
                current = executor.snapshot()[0]
                executor.arm(500,500,True,quantities=current.get("quantities",quantities),enable_mym=current.get("enable_mym",False))
                st.success("Armed for new signals only.")
            except Exception as error:
                st.error(str(error))
    with st.expander("Emergency close"):
        st.warning("Pauses entries and requests a market close of the bot-owned Practice position. No leader/follower orders. Uncertain or unowned positions require manual review.")
        confirm = st.checkbox("Confirm closing the bot-owned Practice position",key="bot_emergency_confirm")
        if st.button("Request emergency close",icon=":material/stop_circle:",disabled=not confirm):
            executor.request_emergency_close(confirm)
            st.warning("Close requested, not yet confirmed. Check broker status below.")


@st.fragment(run_every="5s")
def operations_status():
    settings,runtime,jobs = executor.snapshot()
    feed,fills = practice_history.snapshot()
    import bot_health
    feed = bot_health.snapshot(feed)
    st.subheader("Execution & protection")
    st.write(runtime.get("message","Worker unavailable"))
    st.caption("Worker: "+ct(runtime.get("updated_at"))+" / Broker: "+ct(feed.get("updated_at")))
    fresh = feed.get("updated_at") and 0 <= (datetime.now(timezone.utc)-datetime.fromisoformat(feed["updated_at"])).total_seconds() <= 45 and not feed.get("error")
    if fresh:
        st.caption(f"Broker-confirmed: {len(feed['positions'])} positions / {len(feed['orders'])} working orders")
    else:
        st.warning("Broker snapshot stale or unavailable. Displayed job state is not proof of current exposure.")
    open_jobs = [j for j in jobs if j["state"] not in ("Closed","Rejected")]
    if open_jobs:
        table(pd.DataFrame([{"Symbol":j.get("symbol"),"State":j["state"],"Actual fill":j.get("fill_price"),"Qty":j.get("filled_quantity",j.get("quantity")),"Stop verified":j.get("protected",False),"Order":str(j.get("order_id","--"))} for j in open_jobs]))
    else:
        st.caption("No unresolved bot orders.")
    observed = [j for j in jobs if j.get("slippage_points") is not None]
    avg = sum(j["slippage_points"]/(1 if j["symbol"]=="MYM" else .25) for j in observed)/len(observed) if observed else None
    a,b,c = st.columns(3)
    a.metric("Avg adverse slippage",f"{avg:+.2f} ticks" if avg is not None else "--")
    b.metric("Rejected attempts",sum(j["state"]=="Rejected" for j in jobs))
    c.metric("Uncertain outcomes",sum(j["state"] in ("Unknown","Intent") for j in jobs))
    delays = [datetime.fromisoformat(j["first_fill_observed_at"]).timestamp()-j["sent_at"] for j in jobs if j.get("first_fill_observed_at") and j.get("sent_at")]
    st.caption(f"Mean submission-to-fill observation: {sum(delays)/len(delays):.1f}s" if delays else "Fill observation delay: awaiting new measured fills")
    st.caption("All saved bot attempts, including connection tests. Slippage compares observed broker average fill against signal entry; negative is favorable.")
    st.subheader("Decision log")
    records = bot_audit.events(60)
    table(pd.DataFrame([{"Time (CT)":ct(r["time"]),"Event":r["kind"],"Reason":r["detail"],"Alert":r["alert_id"]} for r in records]),height=270)


def timeline():
    jobs = executor.snapshot()[2]
    st.subheader("Trade review")
    if not jobs:
        st.caption("No order attempts recorded.")
        return
    by_id = {j["alert_id"]:j for j in jobs}
    ordered = sorted(by_id,key=lambda key:by_id[key].get("sent_at",0),reverse=True)
    selected = st.selectbox("Order attempt",ordered,format_func=lambda key:f"#{key} / {by_id[key].get('symbol','--')} / {by_id[key]['state']}")
    job = by_id[selected]
    from executed_results import results
    result = results(jobs,practice_history.snapshot()[1]).get(selected)
    a,b,c,d = st.columns(4)
    a.metric("Signal entry",str(job.get("signal_entry","--")))
    b.metric("Broker fill",str(job.get("fill_price","--")))
    c.metric("Net after costs",f"${result['net']:,.2f}" if result else "Unmatched / open")
    d.metric("Reported costs",f"${result['costs']:,.2f}" if result else "--")
    from signal_lifecycle import alert_history
    signal = next((r for r in alert_history(10000) if r["id"]==selected),{})
    if signal:
        left,right = st.columns(2)
        left.markdown("**Setup evidence**")
        left.text(signal.get("trigger_detail") or signal.get("reason") or "Not recorded")
        right.markdown("**Exit evidence**")
        right.text(signal.get("exit_reason") or signal.get("management_status") or "Not recorded")
        right.text(signal.get("exit_evidence") or "")
    records = bot_audit.events(1000,alert_id=selected)
    with closing(executor.db()) as conn:
        legacy = conn.execute("SELECT recorded_at,record FROM practice_job_events WHERE alert_id=?",(selected,)).fetchall()
    history = [{"time":r[0],"kind":"Recorded order state","detail":json.loads(r[1]).get("state")} for r in legacy]
    history += records
    if history:
        table(pd.DataFrame([{"Time (CT)":ct(r["time"]),"Event":r["kind"],"Evidence":r["detail"]} for r in sorted(history,key=lambda r:r["time"])]))
    st.caption("Signal trail changes are software exit levels, not amendments to the broker backup stop. Historical details before audit logging may be unavailable.")


@st.fragment(run_every="5s")
def notifications(account_profile="practice"):
    unread = bot_audit.events(200,unread=True,account=account_profile)
    st.subheader(f"Notifications ({len(unread)} unread)")
    st.caption("Persistent in-app inbox / Order and protection events / No external delivery configured")
    if unread and st.button("Mark all read",icon=":material/done_all:"):
        bot_audit.acknowledge(max(r["id"] for r in unread),account=account_profile)
        st.rerun(scope="fragment")
    for row in unread[:30]:
        text = f"{ct(row['time'])} | {row['kind']} | {row['detail']}"
        if row["severity"] in ("warning","critical"):
            st.warning(text)
        else:
            st.info(text)
    if not unread:
        st.caption("No unread notifications.")
    with st.expander("Notification archive"):
        table(pd.DataFrame([{"Time (CT)":ct(r["time"]),"Event":r["kind"],"Detail":r["detail"]} for r in bot_audit.events(200,account=account_profile) if r["kind"] in ("Order state","Broker fill","Exit decision","Broker unavailable","Close requested","Flat confirmed")]))


def replay():
    import bot_replay
    from dashboard_view import statistics
    st.subheader("Replay lab")
    st.caption("Offline only / Saved 1-minute candles / No orders or changes to running strategies")
    with st.form("replay_configuration"):
        a,b,c = st.columns(3)
        symbol = a.selectbox("Instrument",["NQ=F","ES=F","YM=F"],format_func=lambda s:{"NQ=F":"MNQ","ES=F":"MES","YM=F":"MYM"}[s])
        strategy = b.selectbox("Strategy",["CRT","Reversal"])
        hours = c.selectbox("Saved history (hours)",[24,48],index=1)
        sessions = st.multiselect("Candidate sessions (CT)",["Regular","Extended","Overnight"],default=["Regular","Extended","Overnight"])
        a,b,c,d = st.columns(4)
        volatility = a.number_input("Max candle / ATR (0 = off)",0.,10.,0.,.5)
        quantity = b.number_input("Contracts",1,4,1,key="replay_qty")
        fees = c.number_input("Round-trip costs / contract ($)",0.,100.,0.,.1)
        slip = d.number_input("Slippage / side (ticks)",0.,20.,1.,.25)
        st.caption("Baseline: current 3-bar / 2-break / 1.5R trail. Candidate CRT: 5-bar / 2-break / 2R; Reversal: 3-bar / 1-break / 1R. Candidate session and volatility filters apply only to its replay.")
        submitted = st.form_submit_button("Compare replay",icon=":material/science:")
    if submitted:
        bars = bot_replay.load_bars(symbol,hours)
        if len(bars) < 30:
            st.warning("Not enough saved complete candles for a replay.")
        else:
            config = dict(symbol=symbol,strategy=strategy,hours=hours,sessions=sessions,max_range_atr=volatility,quantity=quantity,fees=fees,slippage_ticks=slip)
            with st.spinner("Comparing recorded price action..."):
                baseline = bot_replay.simulate(bars,symbol,strategy,quantity=quantity,fees=fees,slippage_ticks=slip)
                candidate = bot_replay.simulate(bars,symbol,strategy,candidate=True,sessions=sessions,max_range_atr=volatility,quantity=quantity,fees=fees,slippage_ticks=slip)
                result = dict(baseline=baseline,candidate=candidate,start=bars.time.min().isoformat(),end=bars.time.max().isoformat())
                st.session_state["last_replay_id"] = bot_replay.save_run(config,result)
    runs = bot_replay.saved_runs()
    if runs:
        lookup = {r["id"]:r for r in runs}
        selected = st.selectbox("Saved replay",list(lookup),format_func=lambda key:f"#{key} / {lookup[key]['config']['strategy']} / {lookup[key]['config']['symbol']} / {ct(lookup[key]['time'])}")
        run = lookup[selected]
        comparison = []
        for name in ("baseline","candidate"):
            value = run["result"][name]
            s = statistics(value["trades"])
            comparison.append({"Model":name.title(),"Trades":s["trades"],"Net ($)":s["net"],"Win %":s["win_rate"],"Profit factor":s["profit_factor"],"Max DD ($)":s["drawdown"],"Expectancy ($)":s["expectancy"],"Open at end":value["open_at_end"]})
        table(pd.DataFrame(comparison))
        st.caption(f"{ct(run['result']['start'])} to {ct(run['result']['end'])}. One symbol/strategy per replay; not a portfolio simulation. OHLC stops are conservative; open end positions excluded. Zero costs means fees are excluded. This is not an exact tick replay or evidence of future returns.")
        candidate = run["result"]["candidate"]
        st.caption("Candidate blocks: "+(" / ".join(f"{key}: {value}" for key,value in candidate["blocks"].items()) or "None"))
        sessions_summary = []
        for name in ("Regular","Extended","Overnight"):
            stats = statistics([r for r in candidate["trades"] if r["session"]==name])
            sessions_summary.append({"Session (CT)":name,"Trades":stats["trades"],"Net ($)":stats["net"],"Win %":stats["win_rate"],"Expectancy ($)":stats["expectancy"]})
        table(pd.DataFrame(sessions_summary))
        with st.expander("Simulated trades"):
            table(pd.DataFrame(candidate["trades"]))
        st.download_button("Download replay",json.dumps(run,indent=2),file_name=f"replay-{selected}.json",mime="application/json",icon=":material/download:")
