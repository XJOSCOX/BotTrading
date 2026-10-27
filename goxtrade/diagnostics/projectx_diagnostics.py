"""Explicit, sanitized read-only ProjectX probes. Never imports broker controls."""
from contextlib import closing
from datetime import datetime,timezone
import json
import os
import sqlite3
import threading
import time
from urllib.parse import urlsplit
import pandas as pd
import requests
from goxtrade.execution import projectx_client as client
from goxtrade.data import live_store
from goxtrade.data.historical_quality import quality,interval
from goxtrade.diagnostics import feed_status

_probe=threading.Lock()
_last=0.
_auth={}
_results=[]

RECOMMENDATIONS={
    "AUTH_FAILED":"Verify the platform username and active API key; no automatic authentication retry is performed.",
    "AUTH_EXPIRED":"A previously issued session was rejected; explicitly test authentication again.",
    "PERMISSION_DENIED":"Check API subscription and required platform agreements with your firm.",
    "RATE_LIMITED":"Wait before another explicit probe; diagnostic retries are bounded.",
    "HISTORY_UNAVAILABLE":"No bars were returned for this contract/range/subscription; this alone is not an outage.",
    "CONTRACT_NOT_FOUND":"Verify the exact active or retained historical contract with the provider.",
    "WEBSOCKET_DISCONNECTED":"Check the independently managed collector; diagnostics never restart it.",
    "SUBSCRIPTION_FAILED":"Collector reported a subscription/stream error; verify provider entitlements.",
    "FEED_STALE":"Compare source timestamps, local receipt and market schedule before allowing entries.",
    "MARKET_CLOSED":"Absence of ticks during closure does not establish a provider outage.",
    "NETWORK_TIMEOUT":"Check connectivity and retry the read-only probe after backoff.",
    "PROVIDER_ERROR":"Provider returned a service error; retry later or contact ProjectX.",
    "MALFORMED_RESPONSE":"Provider data did not match the expected schema; do not use it for trading.",
    "UNKNOWN_ERROR":"Evidence is insufficient to identify a cause; inspect sanitized diagnostics.",
    "CONFIG_INVALID":"Configure valid HTTPS ProjectX URLs and local credential/profile/contract settings.",
    "OK":"Read-only probe succeeded; this does not authorize trading or prove all services are healthy.",
}


def result(category,code,**facts):
    return dict(category=category,code=code,time=datetime.now(timezone.utc).isoformat(),
                recommendation=RECOMMENDATIONS[code],**facts)


def endpoint(value):
    try:
        url=urlsplit(value)
        port=url.port
    except ValueError:return dict(valid=False,host="invalid / withheld")
    host=url.hostname or ""
    valid=(url.scheme=="https" and not url.username and not url.password and not url.query and not url.fragment
           and (host=="topstepx.com" or host.endswith(".topstepx.com") or host=="projectx.com" or host.endswith(".projectx.com")) and port in (None,443))
    return dict(valid=valid,host=host if valid else "invalid / withheld")


def configuration():
    from goxtrade.config.execution_identity import current_targets
    from goxtrade.execution.contracts import symbols_with_contracts
    try:
        targets=current_targets()
        profiles={p:(type(t.get("id")) is int and t["id"]>0 and isinstance(t.get("name"),str)
                     and bool(t["name"].strip()) and not t["name"].startswith("YOUR_")) for p,t in targets.items()}
    except (ValueError,KeyError):profiles=dict(practice=False,leader=False)
    try:mappings=[dict(symbol=r["symbol"],contract_id=r["contract_id"]) for r in symbols_with_contracts(["NQ=F","ES=F","YM=F","MNQ=F","MES=F","MYM=F"])]
    except Exception:mappings=[]
    api=endpoint(client.api_url());hub=endpoint(client.market_hub_url())
    credentials=dict(username_present=bool(os.getenv("TOPSTEP_USERNAME","").strip()),api_key_present=bool(os.getenv("TOPSTEP_API_KEY","").strip()))
    valid=api["valid"] and hub["valid"] and all(profiles.values()) and all(credentials.values()) and bool(mappings)
    return result("configuration","OK" if valid else "CONFIG_INVALID",api=api,market_hub=hub,profiles=profiles,contracts=mappings,**credentials)


def passive(now=None):
    """Read-only live evidence. No authentication, subscription, worker or DB writes."""
    from goxtrade.research.portfolio_backtest import session_facts
    stamp=pd.Timestamp(now or datetime.now(timezone.utc))
    facts=session_facts(stamp)
    # Entry cutoff is separate from exchange closure: flatten can mean account cutoff.
    from goxtrade.strategies.previous_day_box_sessions import session_windows
    from goxtrade.strategies.previous_day_box_config import PreviousDayBoxConfig
    opened=any(a<=stamp<b for w in session_windows(stamp,PreviousDayBoxConfig()) for a,b in w["segments"])
    telemetry=feed_status.read()
    records=[]
    if live_store.DB_PATH.exists():
        try:
            with closing(sqlite3.connect(live_store.DB_PATH.as_uri()+"?mode=ro",uri=True,timeout=.15)) as conn:
                conn.row_factory=sqlite3.Row
                if conn.execute("SELECT 1 FROM sqlite_master WHERE name='live_ticks'").fetchone():
                    rows=conn.execute("SELECT symbol,contract_id,event_time,received_at,price,event_type FROM live_ticks ORDER BY id DESC LIMIT 2000").fetchall()
                    seen=set()
                    for row in rows:
                        key=(row["symbol"],row["event_type"])
                        if key in seen:continue
                        seen.add(key)
                        record=dict(row);record["kind"]=record.pop("event_type");records.append(record)
        except sqlite3.Error:pass
    source=[pd.to_datetime(r["event_time"],utc=True,errors="coerce") for r in records]
    receipts=[pd.to_datetime(r["received_at"],utc=True,errors="coerce") for r in records]
    source=[s for s in source if pd.notna(s)];receipts=[s for s in receipts if pd.notna(s)]
    future_source=bool(source and max(source)>stamp)
    age=(stamp-max(source)).total_seconds() if source and not future_source else None
    connection=telemetry.get("state","unknown / collector telemetry unavailable")
    pid=telemetry.get("pid")
    if pid:
        from goxtrade.runtime.live_process import _pid_running
        if not _pid_running(pid):connection="disconnected / recorded collector no longer running"
    codes=[]
    if future_source:codes.append("MALFORMED_RESPONSE")
    if not opened:codes.append("MARKET_CLOSED")
    if connection.startswith("disconnected"):codes.append("WEBSOCKET_DISCONNECTED")
    if telemetry.get("error_code") in RECOMMENDATIONS:codes.append(telemetry["error_code"])
    if opened and (age is None or age>30):codes.append("FEED_STALE")
    return dict(market_open=opened,entry_allowed=facts["allow_entry"],market_codes=codes,connection=connection,
        subscriptions=telemetry.get("subscriptions",[]),reconnection_attempts=telemetry.get("reconnection_attempts"),
        last_events=records,last_event_timestamp=max(source).isoformat() if source else None,
        last_local_receipt=max(receipts).isoformat() if receipts else None,source_age_seconds=age,
        telemetry_at=telemetry.get("updated_at"),future_source_timestamp=future_source,
        last_stream_error=telemetry.get("last_error_code"),last_stream_error_at=telemetry.get("last_error_at"),
        inspection_window="Last 2000 local events; absent instruments are unknown, not healthy",recommendations=[RECOMMENDATIONS[c] for c in codes])


def classify(status,auth=False):
    if status==401:return "AUTH_FAILED" if auth else "AUTH_EXPIRED"
    if status==403:return "PERMISSION_DENIED"
    if status==404:return "CONTRACT_NOT_FOUND" if not auth else "CONFIG_INVALID"
    if status==429:return "RATE_LIMITED"
    if status>=500:return "PROVIDER_ERROR"
    return "UNKNOWN_ERROR"


def _request(path,payload,token=None,transport=None,sleep=time.sleep):
    transport=transport or requests.post
    if path not in ("/api/Auth/loginKey","/api/History/retrieveBars","/api/Contract/searchById"):
        raise ValueError("Diagnostics endpoint is not read-only allowlisted")
    auth=path.endswith("loginKey")
    if not endpoint(client.api_url())["valid"] or urlsplit(client.api_url()).path not in ("","/"):
        return None,result("authentication" if auth else "history","CONFIG_INVALID")
    began=time.monotonic()
    for attempt in range(1 if auth else 3):
        try:
            response=transport(client.api_url()+path,json=payload,headers={"Content-Type":"application/json",**({"Authorization":"Bearer "+token} if token else {})},timeout=10,allow_redirects=False)
            status=response.status_code
            if status!=200:
                code=classify(status,auth)
                if status in (429,500,502,503,504) and not auth and attempt<2:
                    sleep(min(5,2**attempt));continue
                return None,result("authentication" if auth else "history",code,http_status=status,duration_ms=round(1000*(time.monotonic()-began),2),attempts=attempt+1)
            try:data=response.json()
            except ValueError:data=None
            if not isinstance(data,dict):return None,result("authentication" if auth else "history","MALFORMED_RESPONSE",http_status=status)
            if data.get("success") is not True:
                code=("AUTH_FAILED" if data.get("errorCode")==3 else "PERMISSION_DENIED" if data.get("errorCode") in (7,9,10) else "UNKNOWN_ERROR") if auth else "UNKNOWN_ERROR"
                return None,result("authentication" if auth else "history",code,http_status=status,provider_code=data.get("errorCode") if type(data.get("errorCode")) is int else None)
            return data,result("authentication" if auth else "history","OK",http_status=status,duration_ms=round(1000*(time.monotonic()-began),2),attempts=attempt+1)
        except (requests.Timeout,requests.ConnectionError):
            if not auth and attempt<2:sleep(2**attempt);continue
            return None,result("authentication" if auth else "history","NETWORK_TIMEOUT",duration_ms=round(1000*(time.monotonic()-began),2),attempts=attempt+1)
        except Exception:return None,result("authentication" if auth else "history","UNKNOWN_ERROR")


def _record(report,began):
    report.setdefault("duration_ms",round(1000*(time.monotonic()-began),2))
    report.setdefault("http_status",None)
    _results.append(report);del _results[:-20]
    return report


def run(values,transport=None,sleep=time.sleep):
    global _last
    if not isinstance(values,dict) or values.get("action") not in ("authenticate","history"):
        raise ValueError("Select an explicit authentication or contract-history probe")
    if set(values)-{"action","symbol","contract_id","start","end","live"}:raise ValueError("Unknown diagnostic fields")
    if not _probe.acquire(blocking=False):raise ValueError("A read-only diagnostic is already running")
    try:
        began=time.monotonic()
        if time.monotonic()-_last<2:raise ValueError("Wait two seconds before another explicit probe")
        _last=time.monotonic()
        if values["action"]=="authenticate":
            _auth.clear()
            if not client.credentials_present():report=result("authentication","CONFIG_INVALID")
            else:
                data,report=_request("/api/Auth/loginKey",dict(userName=os.getenv("TOPSTEP_USERNAME"),apiKey=os.getenv("TOPSTEP_API_KEY")),transport=transport,sleep=sleep)
                if data and isinstance(data.get("token"),str) and data["token"].strip():
                    _auth.update(token=data["token"],at=report["time"])
                elif data:report=result("authentication","MALFORMED_RESPONSE")
        else:
            if not _auth.get("token"):raise ValueError("Run a successful explicit authentication test first")
            from goxtrade.market.instruments import validate_contract_instrument
            validate_contract_instrument(values.get("symbol"),values.get("contract_id"))
            start,end=interval(values.get("start"),values.get("end"))
            if end-start>pd.Timedelta(minutes=60) or end>pd.Timestamp.now(tz="UTC").floor("min") or type(values.get("live",False)) is not bool:
                raise ValueError("Select a finalized past history interval of at most 60 minutes and a boolean subscription")
            identity,report=_request("/api/Contract/searchById",dict(contractId=values["contract_id"]),_auth["token"],transport,sleep)
            if identity is None:
                if report["code"]=="AUTH_EXPIRED":_auth.clear()
                return _record(report,began)
            contract=identity.get("contract")
            if contract is None:return _record(result("history","CONTRACT_NOT_FOUND",http_status=200),began)
            from goxtrade.market.instruments import instrument
            product=instrument(values["symbol"])
            if not isinstance(contract,dict) or contract.get("id")!=values["contract_id"] or contract.get("tickSize")!=product.tick_size or contract.get("tickValue")!=product.tick_value:
                return _record(result("history","MALFORMED_RESPONSE",contract_verified=False,http_status=200),began)
            data,report=_request("/api/History/retrieveBars",dict(contractId=values["contract_id"],live=values.get("live",False),startTime=start.isoformat(),endTime=end.isoformat(),unit=2,unitNumber=1,limit=100,includePartialBar=False),_auth["token"],transport,sleep)
            report.update(contract_verified=True,contract_id=values["contract_id"],tick_size=product.tick_size,tick_value=product.tick_value)
            if report["code"]=="AUTH_EXPIRED":_auth.clear()
            if data:
                bars=data.get("bars")
                if not isinstance(bars,list) or len(bars)>100:report=result("history","MALFORMED_RESPONSE")
                elif not bars:report={**report,"code":"HISTORY_UNAVAILABLE","recommendation":RECOMMENDATIONS["HISTORY_UNAVAILABLE"],"candles":0}
                else:
                    try:
                        frame=pd.DataFrame([dict(time=r.get("t"),open=r.get("o"),high=r.get("h"),low=r.get("l"),close=r.get("c"),volume=r.get("v")) for r in bars])
                        frame=frame.sort_values("time")
                        evidence=quality(frame,dict(symbol=values["symbol"],contract_id=values["contract_id"],start=start.isoformat(),end=end.isoformat(),granularity=1))
                        report.update(candles=len(frame),contract_id=values["contract_id"],start=start.isoformat(),end=end.isoformat(),quality=evidence)
                        if evidence["status"] in ("invalid","unsupported"):report.update(code="MALFORMED_RESPONSE",recommendation=RECOMMENDATIONS["MALFORMED_RESPONSE"])
                    except (ValueError,TypeError,AttributeError):report=result("history","MALFORMED_RESPONSE")
        return _record(report,began)
    finally:_probe.release()


def overview():
    from goxtrade.diagnostics.operational_evidence import overview as operational
    from goxtrade.diagnostics.practice_readiness import collect as practice_readiness
    return dict(configuration=configuration(),feed=passive(),results=list(_results),
                authenticated=bool(_auth.get("token")),authenticated_at=_auth.get("at"),broker_execution=False,
                operational=operational(),practice_readiness=practice_readiness())
