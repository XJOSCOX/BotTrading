"""Collector telemetry excludes URLs, tokens and server-supplied error text."""
import json
import os
from goxtrade.data import live_store
from goxtrade.data.lab_store import now


def path():return live_store.DB_PATH.parent/"market_feed_health.json"


def read():
    try:return json.loads(path().read_text(encoding="utf-8"))
    except (OSError,ValueError):return {}


def update(state,*,subscriptions=None,error=None,reconnect=False):
    record=read()
    record.update(state=state,updated_at=now(),pid=os.getpid())
    if subscriptions is not None:record["subscriptions"]=[dict(symbol=r["symbol"],contract_id=r["contract_id"],state="requested / not provider-acknowledged") for r in subscriptions]
    if reconnect:record["reconnection_attempts"]=record.get("reconnection_attempts",0)+1
    record["error_code"]=error
    if error:record.update(last_error_code=error,last_error_at=now())
    path().parent.mkdir(parents=True,exist_ok=True)
    temporary=path().with_suffix(".tmp")
    temporary.write_text(json.dumps(record),encoding="utf-8")
    temporary.replace(path())
