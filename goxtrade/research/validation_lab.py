"""Reproducible orchestration of existing causal engines; no broker dependencies."""
from dataclasses import replace
from contextlib import closing
import copy
import json
import math
import subprocess
import pandas as pd

from goxtrade.paths import ROOT
from goxtrade.data import lab_store as store
from goxtrade.data.historical_quality import quality, interval
from goxtrade.execution.execution_policy import ExecutionPolicy
from goxtrade.execution.profit_policy import ProfitPolicy
from goxtrade.execution.trade_candidate import digest
from goxtrade.strategies.strategy_catalog import SPECS, strategy_spec
from goxtrade.research.portfolio_backtest import run_portfolio_backtest, candidates_at
from goxtrade.research.exit_policy_comparison import compare_exits, diagnostics
from goxtrade.research.market_regimes import classify, session
from goxtrade.research.metrics import statistics, breakdown


def revision():
    commit = subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    dirty = bool(subprocess.check_output(["git","status","--porcelain"],cwd=ROOT,text=True).strip())
    return dict(commit=commit,dirty=dirty)


def validate_request(values):
    allowed = {"datasets","strategies","start","end","initial_balance","execution","exit_policy","configurations","session","compare_exits","compare_portfolios","walk_forward","sensitivity"}
    if not isinstance(values,dict) or set(values)-allowed:
        raise ValueError("Unknown validation request fields")
    if not {"start","end"} <= set(values):
        raise ValueError("Explicit test interval required")
    result = copy.deepcopy(values)
    if not isinstance(values.get("datasets"),list) or not 1 <= len(values["datasets"]) <= 6 or len(set(values["datasets"])) != len(values["datasets"]):
        raise ValueError("Select one to six unique contract datasets")
    selected = values.get("strategies",[])
    if not selected or len(set(selected)) != len(selected) or any(strategy_spec(s).id != s for s in selected):
        raise ValueError("Select canonical registered strategies")
    start,end = interval(values["start"],values["end"])
    balance = values.get("initial_balance",50000.)
    if isinstance(balance,bool) or not isinstance(balance,(float,int)) or not math.isfinite(balance) or balance <= 0:
        raise ValueError("Positive finite simulated initial balance required")
    if values.get("session","all") not in ("all","Regular","Overnight"):
        raise ValueError("Select all, Regular or Overnight research")
    for name in ("compare_exits","compare_portfolios","walk_forward","sensitivity"):
        if type(values.get(name,False)) is not bool:
            raise ValueError("Comparison flags must be booleans")
    configs = values.get("configurations",{})
    if not isinstance(configs,dict) or set(configs)-set(selected):
        raise ValueError("Configuration keys must match selected registered strategies")
    for strategy, config in configs.items():
        if strategy == "vwap_ema_cross":
            from goxtrade.strategies.vwap_ema_config import VwapEmaConfig
            settings = VwapEmaConfig.from_dict(config)
            if settings.entry_mode != "CONFIRMED":
                raise ValueError("Unsupported minute replay: realtime/anticipatory entries require recorded ordered trade ticks")
        elif strategy == "previous_day_box":
            from goxtrade.strategies.previous_day_box_config import PreviousDayBoxConfig
            PreviousDayBoxConfig.from_dict(config)
        elif set(config)-{"management_minutes","orb_minutes"}:
            raise ValueError("Legacy strategy rules/timeframes remain registered; only management/ORB settings are accepted")
        elif any(type(value) is not int or value not in ({5,10,15} if key=="management_minutes" else {5,15,30}) for key,value in config.items()):
            raise ValueError("Unsupported legacy management or opening-range interval")
    meta = [store.get("lab_datasets",identifier) for identifier in values["datasets"]]
    if len({m["symbol"] for m in meta}) != len(meta):
        raise ValueError("One actual contract per instrument; split rollover runs")
    raw = values.get("execution",{})
    settings = ExecutionPolicy.from_dict({**raw,"symbols":[m["symbol"] for m in meta],"monitoring":selected,"participating":selected,"priority":raw.get("priority",selected),"paper_enabled":False})
    if settings.commission_per_side is None:
        raise ValueError("Explicit research commission required")
    if settings.mode == "evidence_research":
        raise ValueError("Uncalibrated evidence ranking is not enabled by the validation lab")
    exit_policy = ProfitPolicy.from_dict(values.get("exit_policy",{}))
    if not exit_policy.enabled:
        exit_policy = replace(exit_policy,enabled=True,mode="baseline")
    return {**result,"start":start.isoformat(),"end":end.isoformat(),"initial_balance":float(balance),"execution":settings.to_dict(),"exit_policy":exit_policy.to_dict(),"configurations":configs,"code":revision()}


def load_datasets(request):
    output, reports = [], []
    for identifier in request["datasets"]:
        meta = store.get("lab_datasets",identifier)
        store.verify_dataset(identifier)
        start,end = interval(request["start"],request["end"])
        if start < pd.Timestamp(meta["start"]) or end > pd.Timestamp(meta["end"]):
            raise ValueError("Test interval extends outside a dataset's requested/verified range")
        # No unbounded tick/minute materialization. Larger histories remain exportable.
        source = store.frame(identifier,start,end,limit=10001)
        if len(source) > 10000:
            raise ValueError("Interactive replay is bounded to 10000 minute bars per instrument; select a smaller test window")
        report = quality(source,{**meta,"start":start.isoformat(),"end":end.isoformat()})
        if not report["eligible"]:
            raise ValueError(f"Dataset {meta['symbol']} is {report['status']}: complete reviewed coverage is required")
        output.append((meta["symbol"],meta["contract_id"],source))
        reports.append(dict(id=identifier,hash=meta["content_hash"],quality=report,expiration=meta.get("expiration"),source=meta["source"]))
    if sum(len(frame) for _,_,frame in output) > 20000:
        raise ValueError("A portfolio replay is bounded to 20000 total source minutes")
    return output,reports


def _source(configurations, selected_session, start=None):
    def source(histories, prices, contracts, now, settings, **identity):
        if start is not None and now < start or selected_session != "all" and session(now) != selected_session:
            return [],[]
        return candidates_at(histories,prices,contracts,now,settings,configurations=configurations,**identity)
    return source


def enrich(result, datasets, initial_balance):
    trades = result["state"]["trades"]
    frames = {s:f for s,_,f in datasets}
    for trade in trades:
        trade["regimes"] = classify(frames[trade["symbol"]],trade["entry_time"])
        trade["trading_session"] = session(trade["entry_time"])
        trade["partial_ineligible"] = trade["quantity"] == 1 and trade.get("exit_policy",{}).get("mode") in ("partial","hybrid")
    equity = result["state"]["equity"]
    peak = 0.
    drawdown = []
    for value in equity:
        peak = max(peak,value)
        drawdown.append(value-peak)
    groups = {}
    for trade in trades:
        for label in trade["regimes"]:
            groups.setdefault(label,[]).append(trade)
    import numpy as np
    counts,edges=np.histogram([row["net"] for row in trades],bins=min(10,max(1,len(trades)))) if trades else ([],[])
    result["lab"] = dict(diagnostics=diagnostics(result),initial_balance=initial_balance,
        ending_marked_balance=initial_balance+equity[-1],equity=[initial_balance+v for v in equity],drawdown=drawdown,
        regimes={label:statistics(rows) for label,rows in groups.items()},sessions=breakdown(trades,"trading_session"),
        months=breakdown(trades,"month"),profit_distribution=[row["net"] for row in trades],
        profit_histogram=[dict(lower=float(edges[i]),upper=float(edges[i+1]),count=int(count)) for i,count in enumerate(counts)],
        peak_risk_utilization_percent=max((row["utilization_percent"] for row in result["state"].get("risk_history",[])),default=0),
        statistical_warning="Insufficient trades for meaningful conclusions" if len(trades)<30 else "Descriptive historical sample; no statistical reliability or future profitability established",
        risk_adjusted=None,planned_open_risk=result["summary"]["planned_open_risk"],
        limitations=["Closed-bar replay; no ordered historical trade ticks", "Original registered timeframes; no optimized strategy ranking",
                     "Open positions are marked, not invented final fills", "Partial exits are ineligible for single contracts; remainder may still trail"])
    return result


def execute(identifier):
    job = store.get("lab_jobs",identifier)
    request = job["request"]
    datasets,reports = load_datasets(request)
    settings, exits = ExecutionPolicy.from_dict(request["execution"]), ProfitPolicy.from_dict(request["exit_policy"])
    configs = request["configurations"]
    source = _source(configs,request.get("session","all"))
    def progress(value, phase="baseline"):
        current = store.get("lab_jobs",identifier)
        if current["cancel"]:
            raise InterruptedError("Research cancelled; previously completed runs preserved")
        store.update_job(identifier,expected_owner=job.get("owner"),progress=float(value),phase=phase)
    result = enrich(run_portfolio_backtest(datasets,settings,configs,candidate_source=source,profit_policy=exits,progress=progress),datasets,request["initial_balance"])
    comparisons = {}
    if request.get("compare_exits"):
        comparisons["exits"] = compare_exits(datasets,settings,configs,candidate_source=source,progress=lambda v:progress(v,"exit policies"))
    if request.get("compare_portfolios"):
        variants = {name:replace(settings,mode=name) for name in ("conservative","first_confirmed","configured_priority")}
        variants.update({"individual:"+s:replace(settings,participating=(s,)) for s in settings.participating})
        variants.update({"positions:"+str(n):replace(settings,max_positions=n,max_group_positions=n) for n in (1,2)})
        variants["risk:75pct"] = replace(settings,max_trade_risk=settings.max_trade_risk*.75)
        comparisons["portfolios"] = {}
        for name, policy in variants.items():
            run = run_portfolio_backtest(datasets,policy,configs,candidate_source=source,profit_policy=exits,progress=lambda v,n=name:progress(v,n))
            comparisons["portfolios"][name] = run["summary"]
    if request.get("sensitivity"):
        comparisons["costs"] = {}
        for name, fees, slip in (("base",settings.commission_per_side,settings.slippage_ticks),("fees +25%",settings.commission_per_side*1.25,settings.slippage_ticks),("slippage +1 tick",settings.commission_per_side,settings.slippage_ticks+1)):
            run = run_portfolio_backtest(datasets,replace(settings,commission_per_side=fees,slippage_ticks=slip),configs,candidate_source=source,profit_policy=exits,progress=lambda v,n=name:progress(v,n))
            comparisons["costs"][name] = run["summary"]
    if request.get("walk_forward"):
        times = sorted(set().union(*(set(pd.to_datetime(f["time"],utc=True)) for _,_,f in datasets)))
        if len(times)<300:
            raise ValueError("Insufficient observations for chronological training/validation/test windows")
        comparisons["chronological"] = []
        bounds = [("training",0,.6),("validation",.6,.8),("test",.8,1.),("rolling test 1",.5,.75),("rolling test 2",.75,1.)]
        for label,a,b in bounds:
            begin,finish = times[int(len(times)*a)],times[min(len(times)-1,int(len(times)*b)-1)]
            sliced = [(s,c,f.loc[pd.to_datetime(f["time"],utc=True)<=finish].copy()) for s,c,f in datasets]
            run = run_portfolio_backtest(sliced,settings,configs,candidate_source=_source(configs,request.get("session","all"),begin),profit_policy=exits,progress=lambda v,n=label:progress(v,n))
            comparisons["chronological"].append(dict(label=label,start=begin.isoformat(),end=finish.isoformat(),parameters_fitted=False,summary=run["summary"],config_hash=digest(configs)))
    record = dict(id=identifier,created_at=store.now(),kind="historical_validation",request=request,datasets=reports,
                  result=result,comparisons=comparisons,broker_checks="NOT_PERFORMED",code=request["code"],recommendation="Capture forward paper observations only after reviewing coverage, costs and unseen-window stability; no broker activation")
    store.save_run(record)
    store.update_job(identifier,expected_owner=job.get("owner"),status="complete",progress=1,result_id=identifier)


def trade_window(run, index):
    if type(index) is not int or not 0 <= index < len(run["result"]["state"]["trades"]):
        raise ValueError("Select a completed historical trade")
    trade = run["result"]["state"]["trades"][index]
    meta = next(item for item in run["datasets"] if item["quality"]["symbol"] == trade["symbol"])
    start = max(pd.Timestamp(meta["quality"]["requested_start"]),pd.Timestamp(trade["entry_time"])-pd.Timedelta(minutes=30))
    end = min(pd.Timestamp(meta["quality"]["requested_end"]),pd.Timestamp(trade["exit_time"])+pd.Timedelta(minutes=30))
    bars = store.frame(meta["id"],start,end,limit=2001)
    if len(bars)>2000:
        bars = bars.iloc[:2000]
    return dict(trade=trade,bars=bars.to_dict("records"),limit=2000)
