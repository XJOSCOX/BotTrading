"""Read-only execution analytics."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import streamlit as st
import practice_executor, practice_history, practice_safety
from executed_results import results
from signal_lifecycle import alert_history

CT = ZoneInfo("America/Chicago")


def statistics(rows):
    values = [r["net"] for r in rows]
    wins, losses = [v for v in values if v>0], [v for v in values if v<0]
    equity = peak = drawdown = 0
    for row in sorted(rows,key=lambda r:r["time"]):
        equity += row["net"]
        peak = max(peak,equity)
        drawdown = max(drawdown,peak-equity)
    return dict(trades=len(values),net=sum(values),costs=sum(r["costs"] for r in rows),
                win_rate=100*len(wins)/len(values) if values else None,
                average_win=sum(wins)/len(wins) if wins else None,
                average_loss=sum(losses)/len(losses) if losses else None,
                expectancy=sum(values)/len(values) if values else None,
                profit_factor=sum(wins)/abs(sum(losses)) if losses else None,drawdown=drawdown)


def usd(value):
    return "--" if value is None else f"{'-' if value<0 else ''}${abs(value):,.2f}"


@st.fragment(run_every="5s")
def render_statistics():
    from dashboard_design import render
    period_col, account_col = st.columns([3,1])
    period = period_col.segmented_control("Period",["Today","7 days","30 days","All saved"],default="All saved",key="dashboard_period_v3",label_visibility="collapsed") or "All saved"
    account = account_col.selectbox("Account",["practice","leader"],format_func=str.title,key="dashboard_account",label_visibility="collapsed")
    if account == "leader":
        import leader_execution
        settings,runtime,jobs = leader_execution.snapshot()
        feed,fills = leader_execution.history()
        gate_id = leader_execution.TARGET["gate_id"]
    else:
        settings,runtime,jobs = practice_executor.snapshot()
        feed,fills = practice_history.snapshot()
        gate_id = 1
    import bot_health
    feed = bot_health.snapshot(feed,account_id=gate_id)
    matched = results(jobs,fills)
    signals = {r["id"]:r for r in alert_history(10000)}
    now = datetime.now(timezone.utc)
    cutoff = None
    if period == "Today":
        cutoff = now.astimezone(CT).replace(hour=0,minute=0,second=0,microsecond=0)
    elif period != "All saved":
        cutoff = now-timedelta(days=7 if period=="7 days" else 30)
    rows = []
    for job in jobs:
        result = matched.get(job["alert_id"])
        if not result:
            continue
        stamp = datetime.fromisoformat(result["closed_at"])
        if cutoff and stamp<cutoff:
            continue
        rows.append({**result,"time":stamp,"symbol":job["symbol"],"strategy":signals.get(job["alert_id"],{}).get("strategy","Unknown"),"direction":"Long" if job["side"]==0 else "Short","quantity":job["quantity"]})
    stale = not feed.get("updated_at") or feed.get("error") or (now-datetime.fromisoformat(feed["updated_at"])).total_seconds()>45
    fresh = runtime.get("updated_at") and (now-datetime.fromisoformat(runtime["updated_at"])).total_seconds()<20
    pending = sum(j["state"]=="Closed" and j["alert_id"]>=0 and j["alert_id"] not in matched for j in jobs)
    render(rows,settings,feed,practice_safety.snapshot(gate_id),stale,fresh,pending)
