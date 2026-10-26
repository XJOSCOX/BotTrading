"""Explicit read-only Practice preflight. No order, arming, worker or risk-reset transport."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import math
import re
from pathlib import Path
import sqlite3
import time

import requests

from goxtrade.config import execution_identity
from goxtrade.data import live_store
from goxtrade.diagnostics import feed_status, projectx_diagnostics
from goxtrade.execution import projectx_client as client
from goxtrade.market.calendar_guard import restriction
from goxtrade.market.market_session import market_session
from goxtrade.market.trading_schedule import execution_schedule


READ_ENDPOINTS = {
    "/api/Account/search": "accounts", "/api/Position/searchOpen": "positions",
    "/api/Order/searchOpen": "orders", "/api/Contract/available": "contracts",
    "/api/Contract/search": "contracts", "/api/History/retrieveBars": "bars",
}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def fresh(value, now, seconds=10):
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp.tzinfo is not None and 0 <= (now-stamp).total_seconds() <= seconds
    except (ValueError, TypeError, AttributeError):
        return False


class Blocked(ValueError):
    """Sanitized preflight failure, never containing raw broker text."""


class ReadOnlyBroker:
    def __init__(self):
        self.token = None
        self.evidence = []

    def authenticate(self):
        started = time.perf_counter()
        self.token = None
        try:
            if not projectx_diagnostics.endpoint(client.api_url())["valid"]:
                raise Blocked("CONFIG_INVALID")
            self.token = client.login()
            if not isinstance(self.token, str) or not self.token.strip():
                raise Blocked("MALFORMED_RESPONSE")
            code = "OK"
        except Exception as error:
            code = error_code(error)
        self.evidence.append(dict(operation="authentication", code=code,
                                  at=datetime.now(timezone.utc).isoformat(),
                                  elapsed_ms=round((time.perf_counter()-started)*1000, 2)))
        return code == "OK"

    def read(self, path, payload):
        if path not in READ_ENDPOINTS or not self.token:
            raise Blocked("READ_ONLY_BOUNDARY")
        started = time.perf_counter()
        code, result, provider_code = "OK", None, None
        try:
            data = client.post(path, payload, token=self.token)
            if not isinstance(data, dict) or type(data.get("success")) is not bool:
                raise Blocked("MALFORMED_RESPONSE")
            provider_code = data.get("errorCode") if type(data.get("errorCode")) is int else None
            if provider_code is None:
                raise Blocked("MALFORMED_RESPONSE")
            if data["success"] is not True or provider_code != 0:
                raise Blocked("PROVIDER_REJECTED")
            rows = data.get(READ_ENDPOINTS[path])
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise Blocked("MALFORMED_RESPONSE")
            if "accountId" in payload and any(row.get("accountId") != payload["accountId"] for row in rows):
                raise Blocked("ACCOUNT_RESPONSE_MISMATCH")
            result = rows
        except Exception as error:
            code = error_code(error)
        self.evidence.append(dict(operation=path, code=code, provider_code=provider_code,
                                  at=datetime.now(timezone.utc).isoformat(),
                                  rows=len(result) if result is not None else None,
                                  elapsed_ms=round((time.perf_counter()-started)*1000, 2)))
        if result is None:
            raise Blocked(code)
        return result


def error_code(error):
    if isinstance(error, Blocked):
        return str(error)
    if isinstance(error, requests.Timeout):
        return "NETWORK_TIMEOUT"
    if isinstance(error, client.ProjectXAuthError):
        return "AUTHENTICATION_UNAVAILABLE"
    if isinstance(error, client.ProjectXResponseError):
        return "MALFORMED_RESPONSE"
    if isinstance(error, requests.RequestException):
        return "NETWORK_OR_PROVIDER_ERROR"
    return "UNAVAILABLE"


def exact_practice(accounts, targets):
    target, leader = targets["practice"], targets["leader"]
    if (target["id"] == leader["id"] or target["name"] == leader["name"]
            or not target["name"].startswith("PRAC-") or target.get("role") != "Not assigned"):
        raise Blocked("DESIGNATED_PRACTICE_IDENTITY_INVALID")
    matches = [a for a in accounts if a.get("id") == target["id"] and a.get("name") == target["name"]]
    if len(matches) != 1:
        raise Blocked("EXACT_ACCOUNT_MATCH_REQUIRED")
    account = matches[0]
    if (type(account.get("id")) is not int or account.get("simulated") is not True
            or account.get("canTrade") is not True or not finite(account.get("balance"))):
        raise Blocked("ACCOUNT_ELIGIBILITY_UNVERIFIED")
    return account


def active_mnq(contracts):
    matches = [c for c in contracts if c.get("symbolId") == "F.US.MNQ" and c.get("activeContract") is True]
    if len(matches) != 1:
        raise Blocked("UNIQUE_ACTIVE_MNQ_REQUIRED")
    contract = matches[0]
    if (not isinstance(contract.get("id"), str) or not re.fullmatch(r"CON\.F\.US\.MNQ\.[HMUZ][0-9]{2}",contract["id"])
            or not finite(contract.get("tickSize")) or contract["tickSize"] != .25
            or not finite(contract.get("tickValue")) or contract["tickValue"] != .5):
        raise Blocked("MNQ_SPECIFICATIONS_INVALID")
    return contract


def local_state(targets):
    """Open production SQLite in read-only mode; never initialize or repair it."""
    with closing(sqlite3.connect(live_store.DB_PATH.as_uri()+"?mode=ro", uri=True, timeout=2)) as conn:
        conn.row_factory = sqlite3.Row
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        profiles = {}
        for profile in ("practice", "leader"):
            control = conn.execute(f"SELECT settings FROM {profile}_control WHERE id=1").fetchone() if profile+"_control" in tables else None
            settings = json.loads(control[0]) if control else {}
            jobs = [json.loads(row[0]) for row in conn.execute(f"SELECT record FROM {profile}_jobs")] if profile+"_jobs" in tables else []
            profiles[profile] = dict(settings=settings, jobs=jobs)
        row = conn.execute("SELECT record FROM practice_loss_gate WHERE id=?", (targets["practice"]["gate_id"],)).fetchone() if "practice_loss_gate" in tables else None
        gate = json.loads(row[0]) if row else None
        row = conn.execute("SELECT record FROM bot_controls WHERE id=?", (targets["practice"]["gate_id"],)).fetchone() if "bot_controls" in tables else None
        policy = json.loads(row[0]) if row else {}
        quote = conn.execute("SELECT * FROM latest_quotes WHERE symbol='MNQ=F'").fetchone() if "latest_quotes" in tables else None
        trade = conn.execute("SELECT * FROM live_ticks WHERE symbol='MNQ=F' AND event_type='trade' ORDER BY id DESC LIMIT 1").fetchone() if "live_ticks" in tables else None
    return dict(profiles=profiles, gate=gate, policy=policy,
                quote=dict(quote) if quote else None, trade=dict(trade) if trade else None)


def collect(broker=None, now=None):
    live_clock = now is None
    now = now or datetime.now(timezone.utc)
    broker = broker or ReadOnlyBroker()
    report = dict(schema_version=1, scope="READ_ONLY_PROVIDER", observed_at=now.isoformat(), profile="practice",
                  checks=[], requests=broker.evidence, actual_orders=0, leader_orders=0,
                  actual_close="NOT_PERFORMED", broker_protection="NOT_TESTED", outcome="BLOCKED")
    def check(name, passed, **facts):
        report["checks"].append(dict(check=name, status="PASS" if passed else "BLOCKED", **facts))
    def finish():
        report["blockers"] = [c["check"] for c in report["checks"] if c["status"] != "PASS"]
        report["provider_calls_successful"] = bool(broker.evidence) and all(r["code"] == "OK" for r in broker.evidence)
        return report
    # Gateway does not document Practice category or bracket mode. Neither a PRAC
    # prefix, simulated=true nor operator approval establishes these provider facts.
    check("independent_provider_practice_category", False, reason="Gateway category discriminator unavailable; name and simulation are not proof")
    check("provider_auto_oco_bracket_mode", False, reason="Account bracket mode is not exposed by the verified account response")
    check("specific_entry_and_separate_close_approvals", False, reason="No order-specific approval obtained")
    try:
        targets = execution_identity.current_targets()
        state = local_state(targets)
        if live_clock:
            # A collector can commit a receipt between the initial clock read and
            # the SQLite snapshot. Observe after the read, never permit future data.
            now = datetime.now(timezone.utc)
            report["observed_at"] = now.isoformat()
        check("execution_process_profile", execution_identity.PROFILE == "practice")
        check("practice_and_leader_paused", all(p["settings"].get("enabled") is False for p in state["profiles"].values()))
        unresolved = sum(j.get("state") not in ("Closed", "Rejected") for p in state["profiles"].values() for j in p["jobs"])
        check("no_unresolved_local_jobs", unresolved == 0, count=unresolved)
        gate = state["gate"] or {}
        check("existing_500_loss_lock", gate.get("account_id") == targets["practice"]["gate_id"]
              and gate.get("locked") is False and finite(gate.get("baseline")), threshold_usd=500, reset=False)
    except Exception:
        check("local_state_readable", False, reason="Saved state unavailable; no files changed")
        return finish()
    schedule = execution_schedule(now)
    session = market_session(now)
    calendar = restriction(now, required=True)
    check("exchange_standard_session", session["is_open"], session=session["name"], holiday_scope="Not established by clock schedule")
    check("existing_execution_schedule", schedule["allow_entry"] and not schedule["flatten"])
    check("reviewed_exchange_calendar", calendar["allow_entry"] and not calendar["flatten"])
    telemetry = feed_status.read()
    check("market_stream_connected", telemetry.get("state") == "connected" and not telemetry.get("error_code"))
    if not broker.authenticate():
        check("authentication", False)
        return finish()
    check("authentication", True)
    try:
        account = exact_practice(broker.read("/api/Account/search", {"onlyActiveAccounts": False}), targets)
        check("exact_designated_identity_and_eligibility", True, category="UNVERIFIED", balance_read=True,
              provider_fields=sorted(k for k in account if k in ("id", "name", "balance", "canTrade", "simulated", "isVisible")))
    except Exception as error:
        check("exact_designated_identity_and_eligibility", False, code=error_code(error))
        return finish()  # Never query another account to fill in missing evidence.
    balance = account["balance"]
    check("current_balance_above_loss_lock", finite(gate.get("baseline")) and gate["baseline"]-balance < 500)
    settings = state["profiles"]["practice"]["settings"]
    start, limit = settings.get("start_balance"), settings.get("max_run_loss")
    check("existing_run_loss_gate", finite(start) and finite(limit) and limit > 0 and start-balance < limit)
    for endpoint, label in (("/api/Position/searchOpen", "broker_positions_flat"), ("/api/Order/searchOpen", "broker_working_orders_clear")):
        try:
            rows = broker.read(endpoint, {"accountId": account["id"]})
            check(label, len(rows) == 0, count=len(rows))
        except Exception as error:
            check(label, False, code=error_code(error))
    contract = None
    try:
        contracts = broker.read("/api/Contract/search", {"searchText": "MNQ", "live": False})
        contract = active_mnq(contracts)
        check("active_mnq_micro_specifications", True, contract=contract["id"], tick_size=.25, tick_value_usd=.5)
    except Exception as error:
        check("active_mnq_micro_specifications", False, code=error_code(error))
    try:
        contracts = broker.read("/api/Contract/available", {"live": False})
        check("available_contracts", contract is not None and any(c.get("id") == contract["id"] for c in contracts), count=len(contracts))
    except Exception as error:
        check("available_contracts", False, code=error_code(error))
    for kind in ("quote", "trade"):
        row = state[kind] or {}
        ready = bool(contract and row.get("contract_id") == contract["id"] and fresh(row.get("event_time"), now)
                     and fresh(row.get("received_at"), now))
        if kind == "quote":
            bid, ask = row.get("best_bid"), row.get("best_ask")
            ready = ready and finite(bid) and finite(ask) and 0 < bid <= ask
        else:
            ready = ready and finite(row.get("price")) and row["price"] > 0
        source = row.get("event_time")
        observed = datetime.fromisoformat(source.replace("Z","+00:00")) if fresh(source,now) else None
        check("fresh_mnq_"+kind, bool(ready), source_at=observed.isoformat() if observed else None,
              source_age_seconds=round((now-observed).total_seconds(),3) if observed else None)
    if contract:
        try:
            end = now.replace(second=0, microsecond=0)
            bars = broker.read("/api/History/retrieveBars", dict(contractId=contract["id"], live=False,
                startTime=(end-timedelta(hours=1)).isoformat(), endTime=end.isoformat(), unit=2, unitNumber=1, limit=60, includePartialBar=False))
            from goxtrade.strategies.vwap_ema_indicators import validate_minutes
            import pandas as pd
            if any(b.get("contractId", contract["id"]) != contract["id"] for b in bars):
                raise Blocked("HISTORY_CONTRACT_MISMATCH")
            frame = validate_minutes(pd.DataFrame([dict(time=b["t"], open=b["o"], high=b["h"], low=b["l"], close=b["c"], volume=b.get("v")) for b in bars], columns=["time", "open", "high", "low", "close", "volume"]))
            if any(frame["time"]+pd.Timedelta(minutes=1) > end):
                raise Blocked("UNFINISHED_HISTORY_BAR")
            check("historical_ohlcv", not frame.empty, count=len(frame), saved_to_production=False)
        except Exception as error:
            check("historical_ohlcv", False, code=error_code(error))
    return finish()


def write_evidence(report, path):
    """Only sanitized report fields are written; identity, balance and tokens stay private."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
    temporary.replace(path)
