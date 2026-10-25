"""SQLite research reservations. Broker authorization is deliberately unavailable."""
from dataclasses import replace
from datetime import datetime, timezone
import json
import sqlite3

from goxtrade.execution.portfolio_risk import Exposure
from goxtrade.execution.strategy_manager import evaluate
from goxtrade.execution.trade_candidate import digest, frozen_json


def initialize(conn):
    if conn.in_transaction:
        raise ValueError("Manager schema initialization requires an idle connection; refusing implicit commit")
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS manager_reservations (
      id TEXT PRIMARY KEY, account TEXT NOT NULL, profile TEXT NOT NULL,
      exposure TEXT NOT NULL, candidate TEXT NOT NULL, setup TEXT NOT NULL,
      status TEXT NOT NULL, record TEXT NOT NULL,
      UNIQUE(account,profile,candidate));
    CREATE UNIQUE INDEX IF NOT EXISTS manager_active_instrument
      ON manager_reservations(account,profile,exposure)
      WHERE status IN ('reserved','intent','unresolved','confirmed','partial');
    CREATE TABLE IF NOT EXISTS manager_reservation_audit (
      id INTEGER PRIMARY KEY AUTOINCREMENT, reservation TEXT NOT NULL,
      time TEXT NOT NULL, status TEXT NOT NULL, reason TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS manager_decisions (
      id TEXT PRIMARY KEY, decision_at TEXT NOT NULL, scope TEXT NOT NULL,
      account TEXT NOT NULL, record TEXT NOT NULL, snapshot TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS manager_settings (id INTEGER PRIMARY KEY CHECK(id=1), record TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS manager_simulation (id TEXT PRIMARY KEY, kind TEXT NOT NULL, record TEXT NOT NULL);
    """)


def persist_decisions(conn, candidates, state, policy, now, decisions, scope):
    safe_candidates = []
    for candidate in candidates:
        record = candidate.to_dict()
        for field in ("config_json", "evidence_json", "risk_json"):
            try:
                record[field] = frozen_json(json.loads(record[field]))
            except (ValueError, TypeError):
                record[field] = '{"invalid_snapshot":"redacted"}'
        safe_candidates.append(record)
    snapshot = frozen_json(dict(candidates=safe_candidates, state=state.to_dict(), policy=policy.to_dict(), now=now, scope=scope))
    for decision in decisions:
        record = decision.to_dict()
        conn.execute("INSERT OR IGNORE INTO manager_decisions VALUES (?,?,?,?,?,?)",
                     (digest(record), decision.decision_at, scope, state.account_id, frozen_json(record), snapshot))


def reserve(conn, candidates, state, policy, now):
    """Capacity and insert share one write transaction; no expiry-based releases."""
    if state.profile not in ("research", "paper"):
        raise ValueError("Manager broker reservations are prohibited; shadow/research only")
    initialize(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        active, consumed, uncertain = [], set(state.consumed), state.unresolved
        for row in conn.execute("SELECT status,record FROM manager_reservations WHERE account=? AND profile=?", (state.account_id, state.profile)):
            record = json.loads(row[1])
            consumed.add(record["setup"])
            if row[0] in ("reserved", "intent", "unresolved", "confirmed", "partial"):
                uncertain |= row[0] in ("intent", "unresolved", "partial")
                if record["candidate"] not in {p.owner for p in (*state.positions, *state.reservations)}:
                    active.append(Exposure(**record["exposure_record"]))
        effective = replace(state, reservations=(*state.reservations, *active), consumed=tuple(sorted(consumed)), unresolved=uncertain)
        decisions = evaluate(candidates, effective, policy, now, scope="paper" if state.profile == "paper" else "historical")
        by_id = {candidate.candidate_id: candidate for candidate in candidates}
        for decision in decisions:
            if not decision.selected:
                continue
            candidate = by_id[decision.candidate_id]
            identifier = digest(dict(account=state.account_id, profile=state.profile, candidate=candidate.candidate_id))
            exposure = Exposure(candidate.symbol, candidate.contract_id, candidate.direction, decision.quantity,
                                candidate.price, candidate.stop, candidate.strategy_id, candidate.candidate_id, protected=True, status="reserved")
            record = dict(id=identifier, account=state.account_id, profile=state.profile, candidate=candidate.candidate_id,
                          setup=candidate.setup_id, decision_at=now, status="reserved", broker_intent=None,
                          broker_order_id=None, reconciliation="simulation_only", exposure_record=exposure.__dict__,
                          candidate_record=candidate.to_dict(), policy=policy.to_dict())
            conn.execute("INSERT INTO manager_reservations VALUES (?,?,?,?,?,?,?,?)",
                         (identifier, state.account_id, state.profile, candidate.exposure, candidate.candidate_id, candidate.setup_id, "reserved", frozen_json(record)))
            conn.execute("INSERT INTO manager_reservation_audit(reservation,time,status,reason) VALUES (?,?,?,?)",
                         (identifier, now, "reserved", "Research capacity reserved atomically; no broker submission"))
        persist_decisions(conn, candidates, effective, policy, now, decisions, "reservation_simulation")
        conn.commit()
        return decisions
    except BaseException:
        conn.rollback()
        raise


def transition(conn, identifier, status, *, reason, order_id=None, now=None):
    """Audited simulation/recovery state machine; uncertain states never auto-retry."""
    allowed = {"reserved": {"intent", "rejected", "unresolved"}, "intent": {"confirmed", "partial", "rejected", "unresolved"},
               "partial": {"confirmed", "closed", "unresolved"}, "unresolved": {"confirmed", "partial", "rejected", "closed"},
               "confirmed": {"closed", "unresolved"}, "closed": set(), "rejected": set()}
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 300:
        raise ValueError("Bounded audited recovery reason required")
    frozen_json(dict(reason=reason))
    now = now or datetime.now(timezone.utc).isoformat()
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT status,record FROM manager_reservations WHERE id=?", (identifier,)).fetchone()
        if row is None or status not in allowed.get(row[0], set()):
            raise ValueError("Invalid reservation transition")
        record = json.loads(row[1])
        if record["profile"] not in ("paper", "research"):
            raise ValueError("Broker reservation recovery is not implemented")
        if status in ("confirmed", "partial") and not order_id:
            raise ValueError("Observed simulation fill identity required")
        record.update(status=status, broker_order_id=order_id or record.get("broker_order_id"), reconciliation=reason)
        conn.execute("UPDATE manager_reservations SET status=?,record=? WHERE id=?", (status, frozen_json(record), identifier))
        conn.execute("INSERT INTO manager_reservation_audit(reservation,time,status,reason) VALUES (?,?,?,?)", (identifier, now, status, reason))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def pending(conn, account, profile):
    return [json.loads(row[0]) for row in conn.execute("SELECT record FROM manager_reservations WHERE account=? AND profile=? AND status NOT IN ('closed','rejected')", (account, profile))]
