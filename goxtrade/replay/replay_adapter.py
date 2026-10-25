"""Actual recorded trade imports and causal tick playback using the shared kernel."""
from contextlib import closing
from io import StringIO
import json
import math
import pandas as pd
from goxtrade.data import lab_store
from goxtrade.data.historical_quality import utc
from goxtrade.execution.trade_candidate import digest,frozen_json
from goxtrade.market.instruments import instrument
from goxtrade.replay import replay_store as store
from goxtrade.research.portfolio_backtest import candidates_at,session_facts
from goxtrade.research.portfolio_forward_paper import advance_portfolio,manage_completed
from goxtrade.research.managed_positions import with_exit_policy


def import_ticks(values):
    if not isinstance(values,dict) or set(values)!={"dataset","source","csv","complete_recording"}:
        raise ValueError("Declare dataset, source, CSV and complete_recording for actual trades")
    if values["complete_recording"] is not True or not isinstance(values["source"],str) or not values["source"].strip():
        raise ValueError("Actual source and complete recording attestation required")
    text=values["csv"]
    if not isinstance(text,str) or not 0<len(text)<=1500000:
        raise ValueError("Actual tick CSV is bounded to 1.5 MB")
    meta=lab_store.get("lab_datasets",values["dataset"])
    lab_store.verify_dataset(meta["id"])
    if not meta["quality"]["eligible"]:raise ValueError("Tick replay requires complete reviewed minute coverage")
    frame=pd.read_csv(StringIO(text),nrows=20001)
    if set(frame.columns)!={"sequence","time","price","volume","contract_id"} or not 0<len(frame)<=20000:
        raise ValueError("Up to 20000 recorded trades with sequence,time,price,volume,contract_id required")
    from goxtrade.research.datasets import validate_ticks
    frame=validate_ticks(frame,meta["contract_id"])
    frame["time"]=[utc(v) for v in frame["time"]]
    if not frame["time"].is_monotonic_increasing or not frame["sequence"].is_monotonic_increasing or frame["sequence"].duplicated().any():
        raise ValueError("Actual trade timestamps and unique source sequences must be ordered")
    if not frame["contract_id"].eq(meta["contract_id"]).all():raise ValueError("Mixed or changed contracts; split rollovers")
    tick=instrument(meta["symbol"]).tick_size
    for row in frame.itertuples():
        if int(row.sequence)!=row.sequence or row.sequence<1 or not math.isfinite(row.price) or row.price<=0 or abs(row.price/tick-round(row.price/tick))>1e-6 or not math.isfinite(row.volume) or row.volume<0:
            raise ValueError("Invalid actual trade sequence, price grid or volume")
    bars=lab_store.frame(meta["id"],limit=10001)
    bars["time"]=pd.to_datetime(bars["time"],utc=True)
    grouped=frame.set_index("time").resample("1min").agg(open=("price","first"),high=("price","max"),low=("price","min"),close=("price","last"),volume=("volume","sum")).dropna().reset_index()
    if len(bars)>10000 or len(grouped)!=len(bars) or not grouped["time"].equals(bars["time"]):
        raise ValueError("Recording must cover exactly the declared complete minute dataset")
    if (grouped[["open","high","low","close","volume"]]-bars[["open","high","low","close","volume"]]).abs().gt(1e-6).any().any():
        raise ValueError("Recorded trade OHLCV does not reconcile to the declared actual minute snapshot")
    records=[dict(sequence=int(r.sequence),time=r.time.isoformat(),price=float(r.price),volume=float(r.volume),contract_id=r.contract_id,symbol=meta["symbol"]) for r in frame.itertuples()]
    record=dict(dataset=meta["id"],dataset_hash=meta["content_hash"],source=values["source"][:180],events=records,granularity="actual_trades")
    record["id"]=digest(record)
    with closing(store.connect()) as conn:
        conn.execute("INSERT OR IGNORE INTO replay_ticks VALUES(?,?)",(record["id"],frozen_json(record)))
        conn.commit()
    return {k:v for k,v in record.items() if k!="events"}|dict(event_count=len(records))


def import_saved_ticks(values):
    """Explicit read-only capture bridge; reconciliation still rejects partial tapes."""
    import sqlite3,time
    from goxtrade.data import live_store
    if not isinstance(values,dict) or set(values)!={"dataset","complete_recording"}:
        raise ValueError("Select dataset and attest actual recording completeness")
    meta=lab_store.get("lab_datasets",values["dataset"])
    if not live_store.DB_PATH.exists():raise ValueError("No saved actual trade observations")
    with closing(sqlite3.connect(live_store.DB_PATH.as_uri()+"?mode=ro",uri=True,timeout=.2)) as conn:
        conn.row_factory=sqlite3.Row
        deadline=time.monotonic()+2
        conn.set_progress_handler(lambda:int(time.monotonic()>deadline),1000)
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='live_ticks'").fetchone():raise ValueError("No saved actual trades")
        try:
            rows=conn.execute("SELECT id sequence,event_time time,price,volume,contract_id FROM live_ticks WHERE contract_id=? AND event_type='trade' AND julianday(event_time)>=julianday(?) AND julianday(event_time)<julianday(?) ORDER BY id LIMIT 20001",
                              (meta["contract_id"],meta["start"],meta["end"])).fetchall()
        except sqlite3.OperationalError:raise ValueError("Captured-trade read exceeded its bounded query budget; import a smaller actual CSV") from None
    if not rows or len(rows)>20000:raise ValueError("No saved actual trades, or more than 20000; split the dataset")
    csv=pd.DataFrame([dict(r) for r in rows]).to_csv(index=False)
    return import_ticks(dict(dataset=meta["id"],complete_recording=values["complete_recording"],source="Explicit local actual-trade capture snapshot",csv=csv))


def tick_step(record,datasets,policy,profit,events):
    from dataclasses import replace
    index=record["next_index"]
    observation=events[index]
    now=pd.Timestamp(observation["time"])
    histories={s:f.loc[f["time"]+pd.Timedelta(minutes=1)<=now].copy() for s,_,f in datasets}
    contracts={s:c for s,c,_ in datasets}
    schedule=session_facts(now)
    state=advance_portfolio(record["state"],[],[observation],policy,now,contracts=contracts,
        session_allowed=schedule["allow_entry"],session_reason=schedule["reason"],flatten=schedule["flatten"],management_histories=histories)
    boundary=now.floor("min").isoformat()
    new_minute=record.get("evaluated_minute")!=boundary
    if new_minute:
        for symbol,frame in histories.items():manage_completed(state,symbol,frame,now)
    config=record["request"]["configurations"].get("vwap_ema_cross",{})
    intrabar="vwap_ema_cross" in policy.participating and config.get("entry_mode","CONFIRMED")!="CONFIRMED"
    current=policy if new_minute else replace(policy,participating=("vwap_ema_cross",) if intrabar else ())
    contexts=None
    observation_state=record.get("vwap_observation",{})
    partials={pd.Timestamp(k):v for k,v in record.get("tick_partials",{}).items()}
    if intrabar:
        from goxtrade.research.datasets import intrabar_snapshot
        from goxtrade.strategies.vwap_ema_config import VwapEmaConfig
        settings=VwapEmaConfig.from_dict(config)
        source=datasets[0][2]
        snapshot=intrabar_snapshot(source,partials,observation,settings.signal_minutes)
        contexts={observation["symbol"]:dict(snapshot=snapshot,sequence=observation["sequence"],observation=observation_state)}
    if current.participating:
        from goxtrade.research.market_regimes import session
        candidates,waits=([],[])
        if record["request"].get("session","all") in ("all",session(now)):
            candidates,waits=candidates_at(histories,{observation["symbol"]:observation["price"]},contracts,now,current,
                account=state["account"],profile="research",configurations=record["request"]["configurations"],recorded_contexts=contexts)
        state["data_rejections"].extend(waits)
        state=advance_portfolio(state,with_exit_policy(candidates,profit),[],policy,now,contracts=contracts,
            session_allowed=schedule["allow_entry"],session_reason=schedule["reason"])
    if contexts:observation_state=contexts[observation["symbol"]]["observation"]
    from goxtrade.execution.trade_candidate import frozen_json
    cutoff=now.floor(f"{config.get('signal_minutes',3)}min")
    partial_state=json.loads(frozen_json({k.isoformat():{**v,"time":pd.Timestamp(v["time"]).isoformat()} for k,v in partials.items() if k>=cutoff}))
    return dict(state=state,next_index=index+1,evaluated_minute=boundary,clock=now.isoformat(),vwap_observation=observation_state,tick_partials=partial_state)
