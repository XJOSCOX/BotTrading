"""Resumable read-only ProjectX minute chunks; no account/order endpoints."""
from datetime import datetime, timezone
import time
import threading
import requests
import pandas as pd

from goxtrade.data import lab_store as store
from goxtrade.data.historical_quality import interval, quality
from goxtrade.execution import projectx_client
from goxtrade.market.instruments import instrument, validate_contract_instrument


class HistoryUnavailable(ValueError):
    pass


class ReadOnlyHistory:
    """Separate request budget, explicit allowlist, bounded existing HTTP timeout."""
    _lock = threading.Lock()
    _last = 0.

    def __init__(self, sleep=time.sleep):
        self.token = None
        self.sleep = sleep

    def bars(self, payload):
        for attempt in range(4):
            try:
                with self._lock:
                    delay = max(0., .75-(time.monotonic()-type(self)._last))
                    self.sleep(delay)
                    type(self)._last = time.monotonic()
                    if self.token is None:
                        self.token = projectx_client.login()
                    data = projectx_client.post("/api/History/retrieveBars",payload,token=self.token)
                if data.get("success") is not True or not isinstance(data.get("bars"),list):
                    raise HistoryUnavailable("Provider refused history or returned an unsupported response; retention/subscription not established")
                return data["bars"]
            except requests.HTTPError as error:
                status = error.response.status_code if error.response is not None else None
                if status == 401 and attempt == 0:
                    self.token = None
                elif status not in (429,500,502,503,504):
                    raise HistoryUnavailable(f"History blocked by provider HTTP {status}; check credentials/subscription/contract") from None
                if attempt == 3:
                    raise HistoryUnavailable(f"History HTTP {status}: bounded retry budget exhausted") from None
                retry = error.response.headers.get("Retry-After","") if error.response is not None else ""
                self.sleep(min(60.,max(2.**attempt,float(retry) if retry.isdigit() else 0)))
            except (requests.Timeout,requests.ConnectionError):
                if attempt == 3:
                    raise HistoryUnavailable("History connection/timeout retry budget exhausted") from None
                self.sleep(2.**attempt)
            except projectx_client.ProjectXAuthError:
                raise HistoryUnavailable("Historical authentication unavailable; verify API credentials/provider access") from None
        raise HistoryUnavailable("History retry budget exhausted")


def request_metadata(values):
    allowed = {"symbol","contract_id","start","end","expiration","calendar_reviewed","calendar_note","live"}
    if not isinstance(values,dict) or set(values)-allowed:
        raise ValueError("Unknown historical request fields")
    if not {"symbol","contract_id","start","end"} <= set(values):
        raise ValueError("Instrument, actual contract and historical interval required")
    symbol = instrument(values["symbol"]).symbol
    validate_contract_instrument(symbol,values["contract_id"])
    if not values["contract_id"].startswith("CON.F.US."):
        raise ValueError("Select an actual ProjectX contract ID, not a continuous symbol")
    start,end = interval(values["start"],values["end"])
    if end > pd.Timestamp.now(tz="UTC").floor("min"):
        raise ValueError("History ends at a finalized past minute")
    if type(values.get("live",False)) is not bool or type(values.get("calendar_reviewed",False)) is not bool:
        raise ValueError("History subscription/calendar flags must be booleans")
    expiration = str(values.get("expiration", ""))
    if expiration:
        pd.Timestamp(expiration)
    return {**values,"symbol":symbol} | dict(start=start.isoformat(),end=end.isoformat(),expiration=expiration,
        source="ProjectX retrieveBars / actual contract / read-only",volume_provenance="Provider historical traded volume",granularity=1,
        timezone="UTC",expiration_provenance="Operator supplied; not inferred from contract code")


def download(identifier, provider=None):
    job = store.get("lab_jobs",identifier)
    meta = job["request"]
    start,end = interval(meta["start"],meta["end"])
    cursor = pd.Timestamp(job["cursor"] or start)
    provider = provider or ReadOnlyHistory()
    while cursor < end:
        if store.get("lab_jobs",identifier)["cancel"]:
            store.update_job(identifier,status="cancelled")
            return
        # At most 1440 one-minute timestamps, safely below the documented 20,000 cap.
        until = min(end,cursor+pd.Timedelta(days=1))
        bars = provider.bars(dict(contractId=meta["contract_id"],live=meta.get("live",False),startTime=cursor.isoformat(),endTime=until.isoformat(),
                                 unit=2,unitNumber=1,limit=20000,includePartialBar=False))
        rows, unique, duplicate_count,observed_order = [], {}, 0,[]
        for raw in bars:
            row = dict(time=raw.get("t"),open=raw.get("o"),high=raw.get("h"),low=raw.get("l"),close=raw.get("c"),volume=raw.get("v"))
            from goxtrade.data.historical_quality import utc
            stamp = utc(row["time"])
            if stamp == until:
                continue  # Provider endpoint inclusivity is normalized to half-open windows.
            row["time"] = stamp.isoformat()
            observed_order.append(row["time"])
            if row["time"] in unique:
                if unique[row["time"]] != row:
                    raise HistoryUnavailable("Conflicting duplicate provider bars; chunk not committed")
                duplicate_count += 1
            unique[row["time"]] = row
        rows = sorted(unique.values(),key=lambda row:row["time"])
        frame = pd.DataFrame(rows,columns=["time","open","high","low","close","volume"])
        report = quality(frame,{**meta,"start":cursor.isoformat(),"end":until.isoformat()})
        if report["status"] == "invalid" or len(bars) >= 20000:
            raise HistoryUnavailable("Invalid or unexpectedly truncated provider chunk; existing data preserved")
        event = dict(start=cursor.isoformat(),end=until.isoformat(),bars=len(rows),duplicates=duplicate_count,provider_order_normalized=observed_order!=sorted(observed_order),retrieved_at=store.now(),source=meta["source"],status=report["status"])
        if not store.stage_chunk(identifier,rows,until.isoformat(),event,owner=job.get("owner")):
            store.update_job(identifier,status="cancelled")
            return
        cursor = until
    data = store.staged_frame(identifier)
    events=store.get("lab_jobs",identifier)["events"]
    saved = store.save_dataset(data,{**meta,"retrieval_job_id":identifier,"retrieval_events":events})
    store.update_job(identifier,expected_owner=job.get("owner"),status="complete",progress=1,result_id=saved["id"],quality=saved["quality"],
                     message="Provider return saved; coverage is independent of requested duration")
