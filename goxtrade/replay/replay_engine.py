"""Incremental replay calls the historical kernel, never a broker adapter."""
import copy
import hashlib
from pathlib import Path
import pandas as pd
from goxtrade.execution.execution_policy import ExecutionPolicy
from goxtrade.execution.profit_policy import ProfitPolicy
from goxtrade.research.portfolio_backtest import run_portfolio_backtest
from goxtrade.research.portfolio_forward_paper import empty_portfolio,portfolio_summary
from goxtrade.research.validation_lab import load_datasets,_source,revision
from goxtrade.paths import ROOT


def code_identity():
    # Content fingerprint also detects uncommitted engine/strategy changes.
    sha=hashlib.sha256()
    for path in sorted((ROOT/"goxtrade").rglob("*.py")):
        sha.update(str(path.relative_to(ROOT)).encode())
        sha.update(path.read_bytes())
    return {**revision(),"content_hash":sha.hexdigest()}


def verify(record):
    current=code_identity()
    if any(current[k]!=record["code"][k] for k in ("commit","content_hash")):
        raise ValueError("Replay code version mismatch; restart as a new session, preserving the original")
    datasets,reports=load_datasets(record["request"])
    keys=("id","hash","expiration","source")
    if [{k:r[k] for k in keys} for r in reports]!=[{k:r[k] for k in keys} for r in record["datasets"]]:
        raise ValueError("Replay dataset identity/provenance mismatch")
    return datasets


def initial(request,reports):
    return dict(request=request,datasets=reports,code=code_identity(),status="paused",speed=1,next_index=0,
        state=empty_portfolio("offline-simulation","research"),checkpoint=None,clock=None,events=[],generation=0,
        created_at=pd.Timestamp.now(tz="UTC").isoformat(),updated_at=pd.Timestamp.now(tz="UTC").isoformat(),broker_execution=False)


def event_delta(before,after,when):
    events=[dict(type="candle_completed",time=when)]
    for key,kind in (("candidates","signal_generated"),("decisions","candidate_decision"),("trades","simulated_exit")):
        for row in after[key][len(before[key]):]:events.append(dict(type=kind,time=row.get("exit_time",row.get("decision_at",row.get("created_at",when))),detail=row))
    positions={p["candidate"]["candidate_id"]:p for p in before["positions"]}
    for position in after["positions"]:
        old=positions.get(position["candidate"]["candidate_id"])
        if not old:events.append(dict(type="simulated_entry",time=position["filled_at"],detail=position["exposure"]))
        elif old["exposure"]["stop"]!=position["exposure"]["stop"]:
            events.append(dict(type="stop_adjustment",time=when,detail=dict(old=old["exposure"]["stop"],new=position["exposure"]["stop"])))
        managed=position.get("trade_management",{})
        oldmanaged=(old or {}).get("trade_management",{})
        for fill in managed.get("fills",[])[len(oldmanaged.get("fills",[])):]:events.append(dict(type="partial_simulated_exit",time=when,detail=fill))
        for decision in managed.get("decisions",[])[len(oldmanaged.get("decisions",[])):]:
            events.append(dict(type="profit_management_decision",time=when,detail=decision))
        if managed.get("target_touched") and not oldmanaged.get("target_touched"):
            events.append(dict(type="target_reached",time=when,detail=dict(target=managed["target"],policy=managed["policy"]["mode"])))
    for trade in after["trades"][len(before["trades"]):]:
        if trade["candidate_id"] not in positions:
            events.append(dict(type="simulated_entry",time=trade["entry_time"],detail=dict(entry=trade["entry"],quantity=trade["quantity"],symbol=trade["symbol"])))
        for fill in trade.get("partial_fills",[])[:-1]:
            events.append(dict(type="partial_simulated_exit",time=fill["time"],detail=fill))
    return events


def step(record,datasets,events=None,prepared=None):
    policy=ExecutionPolicy.from_dict(record["request"]["execution"])
    profit=ProfitPolicy.from_dict(record["request"]["exit_policy"])
    before=record["state"]
    record={**record,"events":list(record["events"])}
    if events is not None:
        from goxtrade.replay.replay_adapter import tick_step
        if record["next_index"]>=len(events):record["status"]="complete";return record
        record.update(tick_step(record,datasets,policy,profit,events))
        total=len(events)
        delta=event_delta(before,record["state"],record["clock"])
        delta[0]["type"]="recorded_trade"
    else:
        cp={**(record["checkpoint"] or {}),"state":before} if record["checkpoint"] else None
        result=run_portfolio_backtest(datasets,policy,record["request"]["configurations"],
            candidate_source=_source(record["request"]["configurations"],record["request"].get("session","all")),
            profit_policy=profit,checkpoint=cp,max_steps=1,prepared=prepared)
        record.update(state=result["state"],checkpoint=result["checkpoint"],next_index=result["checkpoint"]["next_index"])
        total=result["total_steps"]
        times=prepared["times"] if prepared else sorted(set().union(*(set(f["time"]) for _,_,f in datasets)))
        record["clock"]=(times[record["next_index"]-1]+pd.Timedelta(minutes=1)).isoformat()
        delta=event_delta(before,record["state"],record["clock"])
    record["events"].extend(delta)
    record["events"].sort(key=lambda e:e["time"])
    record["events"]=record["events"][-5000:]
    record["total_steps"]=total
    day=record["state"]["day"]
    marked=record["state"]["equity"][-1]
    if record.get("drawdown_day")!=day:
        record.update(drawdown_day=day,daily_peak=marked,daily_drawdown=0.)
    record["daily_peak"]=max(record["daily_peak"],marked)
    record["daily_drawdown"]=max(record["daily_drawdown"],record["daily_peak"]-marked)
    if record["next_index"]>=total:record["status"]="complete"
    return record


def account(record):
    state=record["state"]
    summary=portfolio_summary(state)
    balance=record["request"]["initial_balance"]
    equity=state["equity"]
    peak=equity[0];drawdown=0
    for value in equity:
        peak=max(peak,value);drawdown=max(drawdown,peak-value)
    return dict(**summary,balance=balance+state["realized"],equity=balance+equity[-1],
        available_risk=max(0,record["request"]["execution"]["max_open_risk"]-summary["planned_open_risk"]),
        daily_realized=state["daily_realized"],consecutive_losses=state["consecutive_losses"],maximum_drawdown=drawdown,
        daily_loss=max(0,-state["daily_realized"]),daily_drawdown=record.get("daily_drawdown",0.),identity="Isolated virtual account / simulated USD")
