from datetime import datetime,timezone
import pandas as pd
import streamlit as st
import leader_execution as leader
import bot_health
import bot_controls
import practice_safety
import bot_audit
import live_theme
from strategy_catalog import STRATEGIES
from bot_workspace import table
from bot_view import ct
from executed_results import results,summary


def invoke(action,**values):
    try:
        leader.command(action,**values)
        st.success("Leader settings updated. Check execution status below.")
    except Exception as error:
        st.error(str(error))


def render():
    left, right = st.columns([1, 2.1], gap="large")
    with left:
        with st.container(key="leader_controls"):
            controls()
    with right:
        activity()


@st.fragment(run_every="5s")
def execution_status():
    settings, runtime, _ = leader.snapshot()
    stamp = runtime.get("updated_at")
    fresh = bool(stamp) and (datetime.now(timezone.utc)-datetime.fromisoformat(stamp)).total_seconds()<45
    live_theme.status(settings.get("enabled"), fresh, runtime.get("message", "Worker not started"))


def controls():
    settings,runtime,jobs = leader.snapshot()
    st.subheader("Trading Combine leader")
    st.caption(leader.TARGET["name"]+" / Simulated Topstep account / Leader orders only")
    execution_status()
    fresh_worker = runtime.get("updated_at") and (datetime.now(timezone.utc)-datetime.fromisoformat(runtime["updated_at"])).total_seconds()<45
    if not fresh_worker and st.button("Start leader monitor",icon=":material/power_settings_new:"):
        leader.start_worker()
        st.info("Worker requested. New entries stay paused; existing bot positions remain managed.")
    policy = bot_controls.read("leader")
    with st.form("leader_sizing"):
        a,b = st.columns(2)
        mnq = a.number_input("MNQ contracts",1,4,settings.get("quantities",{}).get("MNQ",3))
        mes = b.number_input("MES contracts",1,4,settings.get("quantities",{}).get("MES",3))
        enable_mym = st.checkbox("Enable MYM trading",value=settings.get("enable_mym") is True,key="leader_enable_mym",help="Applies to new leader entries when saved. Existing positions remain managed.")
        mym = st.number_input("MYM contracts",1,4,settings.get("quantities",{}).get("MYM",3))
        cooldown = st.number_input("Leader cooldown (minutes)",1,60,policy["cooldown_minutes"])
        strategies = st.multiselect("Leader strategies",STRATEGIES,default=policy["strategies"])
        if st.form_submit_button("Save leader settings",icon=":material/save:"):
            invoke("configure",quantities=dict(MNQ=mnq,MES=mes,MYM=mym),strategies=strategies,cooldown=cooldown,enable_mym=enable_mym)
    st.caption("One position per symbol, up to three symbols. First entry: selected size; additional symbols: 1 contract each. Strategy-based exits.")
    with st.expander("Account & copy safeguards"):
        st.write("Topstep handles follower copies. This app does not submit follower orders or verify copier configuration. The $500 lock applies to the leader, not combined follower losses.")
    gate = practice_safety.snapshot(leader.TARGET["gate_id"])
    st.caption(f"Account loss lock: USD 500 / Recorded loss: USD {gate.get('loss',0):,.2f}")
    if gate.get("locked"):
        st.error("Leader loss lock is active. Explicit confirmation is required to reset the baseline.")
    with st.expander("Start leader trading"):
        confirmed = st.checkbox("I authorize automatic trading on "+leader.TARGET["name"],key="leader_authorize")
        copier = st.checkbox("I verified Topstep leader/follower copying, protective brackets, and no manual trading on this account.",key="leader_copy_confirm")
        acknowledge = st.checkbox("I acknowledge the $500 loss and authorize resetting the leader loss baseline.",key="leader_loss_ack") if gate.get("locked") else False
        fresh = runtime.get("updated_at") and (datetime.now(timezone.utc)-datetime.fromisoformat(runtime["updated_at"])).total_seconds()<45
        if st.button("Start leader trading",icon=":material/play_arrow:",disabled=not confirmed or not copier or not fresh or bool(settings.get("enabled"))):
            invoke("arm",confirmed_account=leader.TARGET["name"],copier_confirmed=copier,acknowledge_loss=acknowledge,quantities=dict(MNQ=mnq,MES=mes,MYM=mym))
    if st.button("Pause leader entries",icon=":material/pause:"):
        invoke("pause")
    with st.expander("Emergency close leader bot position"):
        confirmation = st.checkbox("Close the bot-owned leader position and pause new entries",key="leader_emergency_ack")
        st.caption("Does not directly close follower positions. Verify copier actions in Topstep. Unowned or uncertain exposure requires manual review.")
        if st.button("Request leader close",disabled=not confirmation,icon=":material/stop_circle:"):
            invoke("emergency",confirmed_account=leader.TARGET["name"])


@st.fragment(run_every="5s")
def activity():
    settings,runtime,jobs = leader.snapshot()
    feed,fills = leader.history()
    health = bot_health.snapshot(feed,account_id=leader.TARGET["gate_id"])
    st.subheader("Activity & results")
    st.caption("Leader account / Executed bot trades")
    stamp = health.get("updated_at")
    fresh = stamp and (datetime.now(timezone.utc)-datetime.fromisoformat(stamp)).total_seconds()<45 and not health.get("error")
    if fresh:
        st.caption(f"Broker {ct(stamp)} / {len(health['positions'])} positions / {len(health['orders'])} working orders")
        if health["positions"]:
            table(pd.DataFrame(health["positions"])[["contractId","type","size","averagePrice"]])
    else:
        st.warning("Leader broker data unavailable or stale. Do not assume the account is flat.")
    matched = results(jobs,fills)
    totals = summary(matched)
    a,b,c,d = st.columns(4)
    a.metric("Winning exits",totals['wins'])
    b.metric("Losing exits",totals['losses'])
    c.metric("Bot net P&L",f"${totals['net']:,.2f}")
    d.metric("Bot costs",f"${sum(r['costs'] for r in matched.values()):,.2f}")
    st.caption("Matched leader bot trades only, after reported costs. Practice and followers excluded.")
    st.subheader("Bot order history")
    records = [{"Time (CT)":ct(datetime.fromtimestamp(j["sent_at"],timezone.utc).isoformat()) if j.get("sent_at") else "--", "Micro":j.get("symbol"),"Qty":j.get("quantity"),"State":j["state"],"Entry":j.get("fill_price"),"Exit":matched.get(j['alert_id'],{}).get('exit_price'),"Net ($)":matched.get(j['alert_id'],{}).get('net'),"Order":str(j.get("order_id","--")),"Sizing":j.get("sizing_reason","--"),"Reason":j.get("error_message") or j.get("close_reason") or "--"} for j in sorted(jobs,key=lambda j:j.get('sent_at',0),reverse=True)]
    if records:
        st.dataframe(live_theme.table(records).format({"Entry":"{:,.2f}","Exit":"{:,.2f}","Net ($)":"{:,.2f}"},na_rep="--"),hide_index=True,width="stretch",height=min(340,38+35*len(records)))
    else:
        st.caption("No bot orders yet.")
    with st.expander("Leader broker fills"):
        st.dataframe(pd.DataFrame([{"Time (CT)":ct(f["creationTimestamp"]),"Contract":f.get("contractId"),"Size":f.get("size"),"Price":f.get("price"),"P&L":f.get("profitAndLoss"),"Fees":f.get("fees"),"Order":str(f.get("orderId"))} for f in fills]),hide_index=True,width="stretch",height=300)
    notices = bot_audit.events(50,account="leader")
    with st.expander("Leader notifications & decisions"):
        table(pd.DataFrame([{"Time (CT)":ct(r["time"]),"Event":r["kind"],"Detail":r["detail"]} for r in notices]))
