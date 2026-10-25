"""Shared native/Streamlit service. Research writes never mutate execution tables."""
from io import StringIO
import pandas as pd
from goxtrade.data import lab_store as store
from goxtrade.data.history_download import request_metadata
from goxtrade.strategies.strategy_catalog import SPECS


def overview():
    from goxtrade.execution.projectx_client import credentials_present
    from goxtrade.execution.manager_service import shared_strategy_configs
    jobs=store.read_rows("lab_jobs")
    for job in jobs:
        job["can_resume"]=job["status"] not in ("running","complete") or (pd.Timestamp.now(tz="UTC")-pd.Timestamp(job["updated_at"])).total_seconds()>600
    return dict(datasets=store.read_rows("lab_datasets"),jobs=jobs,runs=store.run_summaries(),
        strategies=[dict(id=s.id,name=s.name,minutes=s.signal_minutes,modes=list(s.modes)) for s in SPECS],configurations=shared_strategy_configs(),
        credentials_present=credentials_present(),provider_history="Unverified until explicit download; independent of live feed/session",
        broker_execution=False,source_limit=20000,replay_limit=10000)


def history(values, start=True):
    from goxtrade.research.lab_jobs import start as launch
    meta = request_metadata(values)
    job = store.job("history",meta)
    return launch(job["id"]) if start else job


def import_csv(values):
    allowed = {"symbol","contract_id","start","end","expiration","calendar_reviewed","calendar_note","csv","source","volume_provenance"}
    if set(values)-allowed:
        raise ValueError("Unknown dataset import fields")
    if not {"symbol","contract_id","start","end","expiration"} <= set(values):
        raise ValueError("Instrument, contract, expiration and source interval required")
    if type(values.get("calendar_reviewed",False)) is not bool or not isinstance(values.get("calendar_note",""),str):
        raise ValueError("Calendar review requires a boolean and a text reference")
    text = values.get("csv","")
    if not isinstance(text,str) or not 0 < len(text) <= 1500000:
        raise ValueError("Upload a nonempty minute CSV up to 1.5 MB")
    if not values.get("source") or not values.get("volume_provenance"):
        raise ValueError("Declare the actual source and volume provenance")
    frame = pd.read_csv(StringIO(text),nrows=60001)
    if len(frame)>60000:
        raise ValueError("CSV import is bounded to 60000 minutes; split large actual datasets")
    columns = [key for key in ("time","open","high","low","close","volume","contract_id","complete") if key in frame]
    frame = frame[columns]
    meta = {key:value for key,value in values.items() if key != "csv"}
    meta.update(timezone="UTC",granularity=1,source="User import: "+str(meta["source"])[:180],volume_provenance=str(meta["volume_provenance"])[:180])
    return store.save_dataset(frame,meta)


def validation(values,start=True):
    from goxtrade.research.validation_lab import validate_request,load_datasets
    from goxtrade.research.lab_jobs import start as launch
    request = validate_request(values)
    load_datasets(request)  # Refuse invalid/partial/oversized histories before queueing.
    job = store.job("validation",request)
    return launch(job["id"]) if start else job


def import_saved(values):
    """Explicit read-only bridge from the existing canonical provider bar store."""
    from contextlib import closing
    from goxtrade.data import live_store
    from goxtrade.market.instruments import instrument
    meta=request_metadata(values)
    symbol=instrument(meta["symbol"]).symbol+"=F"
    with closing(live_store.connect()) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='strategy_historical_minutes'").fetchone():
            raise ValueError("No canonical contract history has been saved; download or import actual data")
        rows=[dict(r) for r in conn.execute("SELECT time,open,high,low,close,volume,retrieved_at FROM strategy_historical_minutes WHERE symbol=? AND contract_id=? AND time>=? AND time<? ORDER BY time LIMIT 60001",(symbol,meta["contract_id"],meta["start"],meta["end"]))]
    if not rows or len(rows)>60000:
        raise ValueError("No saved rows or more than 60000 minutes; select an available smaller interval")
    if any(not row["retrieved_at"] for row in rows):
        raise ValueError("Legacy saved history lacks retrieval provenance; obtain verified provider bars")
    meta["source_retrieval_range"]=[min(row["retrieved_at"] for row in rows),max(row["retrieved_at"] for row in rows)]
    meta["source"]="Existing canonical ProjectX minute history / explicit research snapshot"
    return store.save_dataset(pd.DataFrame(rows).drop(columns="retrieved_at"),meta)
