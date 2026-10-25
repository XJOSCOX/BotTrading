"""Bounded, read-only local acceptance evidence; no provider or worker operations."""
from contextlib import closing
from datetime import datetime, timezone
import json
import os
import sqlite3
import time

from goxtrade.config import execution_identity
from goxtrade.data import live_store, lab_store
from goxtrade.strategies.strategy_catalog import SPECS


def _object(value):
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("Invalid evidence object")
    return parsed


def _read(path, reader):
    if not path.exists():
        return dict(storage="MISSING", evidence=None)
    try:
        with closing(sqlite3.connect(path.as_uri()+"?mode=ro", uri=True, timeout=.15)) as conn:
            deadline = time.monotonic()+.2
            conn.set_progress_handler(lambda: int(time.monotonic()>deadline), 1000)
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            return dict(storage="READABLE", evidence=reader(conn, tables))
    except (sqlite3.Error, ValueError, TypeError, KeyError, AttributeError):
        return dict(storage="UNAVAILABLE", evidence=None, reason="Local evidence unavailable; saved state preserved")


def _fresh(value, now):
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp.tzinfo is not None and 0 <= (now-stamp).total_seconds() <= 30
    except (ValueError, TypeError, AttributeError):
        return False


def _row(conn, tables, table, key):
    if table not in tables:
        return None
    row = conn.execute(f"SELECT record FROM {table} WHERE id=?", (key,)).fetchone()
    return _object(row[0]) if row else None


def _production(conn, tables, now, targets):
    profiles = {}
    parameters = {}
    if "strategy_parameters" in tables:
        parameters = {row[0]: _object(row[1]) for row in conn.execute(
            "SELECT strategy_id,record FROM strategy_parameters WHERE strategy_id IN ('vwap_ema_cross','previous_day_box')")}
    for profile in ("practice", "leader"):
        target = targets[profile]
        settings = None
        if profile+"_control" in tables:
            row = conn.execute(f"SELECT settings FROM {profile}_control WHERE id=1").fetchone()
            settings = _object(row[0]) if row else None
        controls = _row(conn, tables, "bot_controls", target["gate_id"])
        gate = _row(conn, tables, "practice_loss_gate", target["gate_id"])
        history = _row(conn, tables, profile+"_history_status", 1)
        recent = bool(history and history.get("account_id") == target["id"] and history.get("error") is False
                      and _fresh(history.get("updated_at"), now) and isinstance(history.get("positions"), list)
                      and isinstance(history.get("orders"), list))
        jobs = None
        if profile+"_jobs" in tables:
            jobs = [_object(row[0]) for row in conn.execute(
                f"SELECT record FROM {profile}_jobs WHERE COALESCE(json_extract(record,'$.state'),'Unknown') NOT IN ('Closed','Rejected') LIMIT 1001")]
        owned = [job for job in jobs or [] if job.get("account_id") == target["id"]]
        profiles[profile] = dict(saved_enabled=settings.get("enabled") if settings and type(settings.get("enabled")) is bool else None,
            selected_strategies=[spec.name for spec in SPECS if controls and spec.name in controls.get("strategies", [])] if controls else None,
            strategy_opt_ins={spec.name: parameters.get(spec.id, {}).get(profile+"_enabled")
                              if type(parameters.get(spec.id, {}).get(profile+"_enabled")) is bool else None
                              for spec in SPECS if spec.id in ("vwap_ema_cross", "previous_day_box")},
            loss_locked=gate.get("locked") if gate and gate.get("account_id") == target["gate_id"] and type(gate.get("locked")) is bool else None,
            broker_snapshot_recent=recent, broker_positions=len(history["positions"]) if recent else None,
            broker_orders=len(history["orders"]) if recent else None,
            unresolved_jobs=len(owned) if jobs is not None else None,
            ambiguous_jobs=sum(job.get("account_id") != target["id"] for job in jobs) if jobs is not None else None,
            saved_stops_verified=sum(job.get("protected") is True for job in owned) if jobs is not None else None,
            jobs_truncated=bool(jobs and len(jobs)>1000), broker_protection="NOT VERIFIED BY THIS PAGE")
    monitor = []
    if "bot_monitor_status" in tables:
        monitor = [(row[0], _object(row[1])) for row in conn.execute("SELECT strategy,record FROM bot_monitor_status LIMIT 100")]
    rejections = {}
    if "manager_decisions" in tables:
        for row in conn.execute("SELECT record FROM manager_decisions ORDER BY rowid DESC LIMIT 300"):
            decision = _object(row[0])
            if decision.get("selected") is False:
                rejections.setdefault(decision.get("strategy_id"), decision)
    # Display existing reasons, never infer a rejection from price movement.
    private = [os.getenv(key, "") for key in ("TOPSTEP_USERNAME", "TOPSTEP_API_KEY")]
    private += [str(value) for target in targets.values() for key, value in target.items() if key in ("id", "name")]
    def safe_reason(value):
        if not isinstance(value, str):
            return None
        for item in private:
            if item:
                value = value.replace(item, "[redacted]")
        return value[:300]
    strategies = []
    for spec in SPECS:
        rows = [record for name, record in monitor if name == spec.name]
        fresh = [r for r in rows if _fresh(r.get("updated_at"), now)]
        signals = [r.get("signal", {}) for r in fresh]
        direction = next((s.get("signal") for s in signals if s.get("signal") in ("LONG", "SHORT")), None)
        reject = rejections.get(spec.id, {})
        reasons = reject.get("reasons", [])
        strategies.append(dict(id=spec.id, name=spec.name, minutes=spec.signal_minutes,
            monitoring="RECENT SNAPSHOT" if fresh else "STALE / UNAVAILABLE",
            quote_fresh=bool(fresh) and all(r.get("feed_fresh") is True and _fresh(r.get("quote_time"), now) for r in fresh),
            history_readiness="NOT ESTABLISHED BY PASSIVE SNAPSHOT",
            latest_signal=direction or ("WAIT" if signals and all(s.get("signal") == "WAIT" for s in signals) else "UNKNOWN"),
            signal_scope="Recent saved monitor observations, not a historical signal ledger",
            last_rejection=safe_reason(reasons[0]) if reasons else None,
            rejection_stage=reject.get("eligibility") if reject.get("eligibility") in
                ("REJECTED", "EXPIRED", "DATA_UNAVAILABLE", "EXECUTION_DISABLED", "RISK_BLOCKED", "CONFLICTED") else None))
    return dict(profiles=profiles, strategies=strategies)


def _research(conn, tables):
    if "lab_schema" in tables and [row[0] for row in conn.execute("SELECT version FROM lab_schema")] != [1]:
        raise ValueError("Unsupported research schema")
    count = conn.execute("SELECT COUNT(*) FROM lab_datasets").fetchone()[0] if "lab_datasets" in tables else None
    eligible = conn.execute("SELECT COUNT(*) FROM lab_datasets WHERE json_extract(record,'$.quality.eligible')=1").fetchone()[0] if count is not None else None
    runs = conn.execute("SELECT COUNT(*) FROM lab_runs").fetchone()[0] if "lab_runs" in tables else None
    row = conn.execute("SELECT record FROM lab_runs ORDER BY rowid DESC LIMIT 1").fetchone() if runs else None
    latest = _object(row[0]) if row else None
    comparisons = latest.get("comparisons", {}) if latest else {}
    return dict(dataset_count=count, eligible_metadata_count=eligible, run_count=runs,
                latest_run_at=latest.get("created_at") if latest else None,
                portfolio_comparison=bool(comparisons.get("portfolios")), exit_comparison=bool(comparisons.get("exits")),
                replay_readiness="METADATA AVAILABLE / VERIFY INTEGRITY ON USE" if eligible else "BLOCKED / VERIFIED DATA UNAVAILABLE",
                source_scope="Saved metadata, not independent source verification or market validation")


def _replays(conn, tables):
    if "replay_schema" in tables and [row[0] for row in conn.execute("SELECT version FROM replay_schema")] != [1]:
        raise ValueError("Unsupported replay schema")
    count = conn.execute("SELECT COUNT(*) FROM replay_sessions").fetchone()[0] if "replay_sessions" in tables else None
    row = conn.execute("SELECT record FROM replay_sessions ORDER BY rowid DESC LIMIT 1").fetchone() if count else None
    record = _object(row[0]) if row else {}
    status = record.get("status")
    return dict(session_count=count, latest_status=status if status in ("paused", "stopped", "playing", "complete") else "UNKNOWN",
                latest_clock=record.get("clock"), broker_execution=False)


def overview(now=None):
    now = now or datetime.now(timezone.utc)
    try:
        targets = execution_identity.current_targets()
        production = _read(live_store.DB_PATH, lambda conn, tables: _production(conn, tables, now, targets))
    except (ValueError, KeyError, TypeError):
        production = dict(storage="UNAVAILABLE", evidence=None, reason="Account configuration unavailable; not verified")
    strategies = production.get("evidence", {}).get("strategies") if production.get("evidence") else None
    if strategies is None:
        strategies = [dict(id=spec.id, name=spec.name, minutes=spec.signal_minutes,
                           monitoring="STALE / UNAVAILABLE", quote_fresh=False,
                           history_readiness="NOT ESTABLISHED BY PASSIVE SNAPSHOT", latest_signal="UNKNOWN",
                           last_rejection=None, rejection_stage=None) for spec in SPECS]
    return dict(observed_at=now.isoformat(), production=production, strategies=strategies,
                research=_read(lab_store.database_path(), _research),
                replay=_read(lab_store.database_path().with_name("offline_replay.db"), _replays),
                restrictions="READ-ONLY EVIDENCE / RESEARCH DOES NOT AUTHORIZE ORDERS / BROKER AMENDMENTS AND PARTIALS DISABLED")
