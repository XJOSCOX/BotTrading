"""Explicit offline controls. Playback never starts from imports or app startup."""
import copy
from functools import lru_cache
import threading
import time
import pandas as pd
from goxtrade.data import lab_store
from goxtrade.replay import replay_store as store,replay_engine as engine
from goxtrade.replay.replay_clock import speed
from goxtrade.research.validation_lab import validate_request,load_datasets
from goxtrade.research.datasets import validate_dataset
from goxtrade.strategies.strategy_catalog import SPECS

_lock=threading.RLock()
_players={}


def overview():
    return dict(sessions=store.summaries(),datasets=lab_store.read_rows("lab_datasets"),
                strategies=[dict(id=s.id,name=s.name,minutes=s.signal_minutes) for s in SPECS],broker_execution=False)


def create(values):
    if not isinstance(values,dict):raise ValueError("Replay configuration required")
    copied=copy.deepcopy(values)
    tick_id=copied.pop("ticks",None)
    # Research-only policy/config parser rejects account IDs and execution permissions.
    request=validate_request(copied,allow_recorded_intrabar=bool(tick_id))
    datasets,reports=load_datasets(request)
    record=engine.initial(request,reports)
    if tick_id:
        pack=store.ticks(tick_id)
        if len(request["datasets"])!=1 or pack["dataset"]!=request["datasets"][0] or pack["dataset_hash"]!=reports[0]["hash"]:
            raise ValueError("Recorded trades must belong to this single immutable contract dataset")
        record["ticks"]=tick_id
    return view(store.create(record))


@lru_cache(maxsize=2)
def loaded(identifier,identity):
    record=store.get(identifier)
    if record["code"]["content_hash"]!=identity:raise ValueError("Replay code identity changed")
    datasets=engine.verify(record)
    datasets=[(s,c,validate_dataset(f,c)) for s,c,f in datasets]
    events=None
    if record.get("ticks"):
        pack=store.ticks(record["ticks"])
        from goxtrade.execution.trade_candidate import digest
        if digest({k:v for k,v in pack.items() if k!="id"})!=pack["id"]:raise ValueError("Recorded trade snapshot integrity mismatch")
        a,b=pd.Timestamp(record["request"]["start"]),pd.Timestamp(record["request"]["end"])
        events=[e for e in pack["events"] if a<=pd.Timestamp(e["time"])<b]
        if not events:raise ValueError("No actual recorded trades in the selected interval")
    from goxtrade.research.portfolio_backtest import prepare_portfolio
    return datasets,events,prepare_portfolio(datasets)


def verified(record):
    current=engine.code_identity()
    if any(current[k]!=record["code"][k] for k in ("commit","content_hash")):
        raise ValueError("Replay code version changed; restart as a new session")
    return loaded(record["id"],current["content_hash"])


def view(record):
    state=record["state"]
    positions=copy.deepcopy(state["positions"])
    from goxtrade.execution.trade_analytics import analytics
    for position in positions:
        managed=position.get("trade_management")
        if managed:
            position["analytics"]=analytics(managed)
            policy=managed["policy"]
            position["hold_evidence"]=dict(exit_policy=policy["mode"],pending_exit=managed["pending_exit"],
                target_touched=managed.get("target_touched",False),remaining=managed["remaining"],
                current_r=managed["current_r"],maximum_r=managed["max_r"],trail_activation_r=policy["trail_start_r"],
                break_even_r=policy["break_even_r"],profit_lock_r=policy["profit_lock_r"],
                baseline=managed["baseline"],latest_decision=managed["decisions"][-1:] or [],
                blocked_reason=managed.get("blocked_reason"),protection=managed["protection_status"])
    return {k:v for k,v in record.items() if k not in ("state","events","checkpoint")}|dict(
        virtual_account=engine.account(record),positions=positions,pending=state["pending"],trades=state["trades"][-200:],
        candidates=state["candidates"][-100:],decisions=state["decisions"][-100:],waits=state["data_rejections"][-30:],events=record["events"][-150:],
        player_alive=bool(_players.get(record["id"]) and _players[record["id"]].is_alive()))


def detail(identifier):
    return view(store.get(identifier))


def chart(identifier,symbol):
    record=store.get(identifier)
    if not record["clock"]:return dict(bars=[],symbol=symbol)
    dataset=next((r for r in record["datasets"] if lab_store.get("lab_datasets",r["id"])["symbol"]==symbol),None)
    if dataset is None:raise ValueError("Select an instrument from this replay")
    until=pd.Timestamp(record["clock"]).floor("min")
    if until<=pd.Timestamp(record["request"]["start"]):return dict(bars=[],symbol=symbol)
    # At most 500 revealed bars; never reveal an uncompleted historical candle.
    frame=lab_store.frame(dataset["id"],max(pd.Timestamp(record["request"]["start"]),until-pd.Timedelta(minutes=500)),until,limit=500)
    if frame.empty:return dict(bars=[],symbol=symbol)
    close=frame["close"]
    frame["ema20"]=close.ewm(span=20,adjust=False).mean()
    frame["ema50"]=close.ewm(span=50,adjust=False).mean()
    # VWAP uses only the current session, not an arbitrary rolling chart window.
    full=lab_store.frame(dataset["id"],record["request"]["start"],until,limit=10000)
    from goxtrade.research.portfolio_forward_paper import trading_day
    full["session"]=[trading_day(pd.Timestamp(t)) for t in full["time"]]
    full["pv"]=((full.high+full.low+full.close)/3)*full.volume
    full["vwap"]=full.groupby("session").pv.cumsum()/full.groupby("session").volume.cumsum().replace(0,float("nan"))
    frame=frame.merge(full[["time","vwap"]],on="time",how="left")
    box=None
    if "previous_day_box" in record["request"]["strategies"]:
        from goxtrade.strategies.previous_day_box_sessions import previous_box
        from goxtrade.strategies.previous_day_box_config import PreviousDayBoxConfig
        try:
            full["time"]=pd.to_datetime(full["time"],utc=True)
            full.attrs["contract_id"]=lab_store.get("lab_datasets",dataset["id"])["contract_id"]
            config=PreviousDayBoxConfig.from_dict(record["request"]["configurations"].get("previous_day_box",{}))
            box=previous_box(full,until,config,full.attrs["contract_id"])
        except (ValueError,TypeError,KeyError):pass
    return dict(bars=frame.astype(object).where(pd.notna(frame),None).to_dict("records"),symbol=symbol,box=box,
                overlay_provenance="Causal EMA20/50; displayed VWAP begins at available session data, not a strategy eligibility override")


def action(identifier,values):
    if not isinstance(values,dict) or set(values)-{"action","speed"}:
        raise ValueError("Unknown replay control fields")
    operation=values.get("action")
    with _lock:
        record=store.get(identifier)
        if operation in ("pause","stop"):
            record.update(status="paused" if operation=="pause" else "stopped",generation=record["generation"]+1)
            record.pop("candle_until",None)
        elif operation=="speed":record["speed"]=speed(values.get("speed"))
        elif operation=="restart":
            request=copy.deepcopy(record["request"])
            request.pop("code",None)
            if record.get("ticks"):request["ticks"]=record["ticks"]
            return create(request)
        elif operation in ("step","candle","play","resume"):
            if operation in ("play","resume") or not _players.get(identifier):loaded.cache_clear()
            datasets,events,prepared=verified(record)
            if record["status"]=="complete":raise ValueError("Replay complete; restart creates a separate session")
            if operation=="candle" and events:
                record.update(status="playing",generation=record["generation"]+1,
                    candle_until=pd.Timestamp(events[record["next_index"]]["time"]).floor("min").isoformat())
            elif operation in ("step","candle"):
                record["generation"]+=1
                record["status"]="paused"
                record.pop("candle_until",None)
                record=engine.step(record,datasets,events,prepared)
            else:
                record.update(status="playing",generation=record["generation"]+1)
                record.pop("candle_until",None)
        else:raise ValueError("Select play, resume, pause, stop, step, candle, speed or restart")
        record=store.save(record)
        if operation in ("play","resume") or operation=="candle" and record["status"]=="playing":
            finished=[key for key,player in _players.items() if not player.is_alive()]
            for key in finished:_players.pop(key,None)
            thread=threading.Thread(target=_play,args=(identifier,record["generation"]),daemon=True,name="offline-replay")
            _players[identifier]=thread;thread.start()
    return view(record)


def _play(identifier,generation):
    last=time.monotonic();credit=0.
    try:
        while True:
            with _lock:
                record=store.get(identifier)
                if record["status"]!="playing" or record["generation"]!=generation:return
                datasets,events,prepared=loaded(identifier,record["code"]["content_hash"])
                now=time.monotonic();elapsed=now-last;last=now
                value="maximum" if record.get("candle_until") else record["speed"]
                credit+=elapsed*(1 if value=="maximum" else value)
                count=0
                while count<5:
                    if events and record.get("candle_until") and pd.Timestamp(events[record["next_index"]]["time"]).floor("min")>pd.Timestamp(record["candle_until"]):
                        record["status"]="paused";record.pop("candle_until",None);store.save(record);return
                    interval=60.
                    if events and record["next_index"]>0 and record["next_index"]<len(events):
                        interval=max(.001,(pd.Timestamp(events[record["next_index"]]["time"])-pd.Timestamp(events[record["next_index"]-1]["time"])).total_seconds())
                    if value!="maximum" and credit<interval:break
                    record=engine.step(record,datasets,events,prepared);count+=1;credit=max(0,credit-interval)
                    if record["status"]=="complete":break
                if count:store.save(record)
                if record["status"]=="complete":return
            time.sleep(.05)
    except Exception:
        # No raw provider, source CSV or account information in persisted failures.
        with _lock:
            record=store.get(identifier)
            if record["generation"]==generation:
                record.update(status="paused",error="Replay stopped safely after a processing or ownership error; verify source/code before resuming")
                store.save(record)
