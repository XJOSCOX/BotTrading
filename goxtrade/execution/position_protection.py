"""Verified API shapes, disabled broker transport and durable mock exit recovery."""
import copy
import json

from goxtrade.execution.trade_candidate import digest, frozen_json, stamp, finite


def take_profit_bracket(payload, *, enabled=False, verified_ticks=None, auto_oco_verified=False, signed_ticks_reviewed=False):
    """Pure adapter only. Official schema accepts TP; signed offset semantics need review."""
    result = copy.deepcopy(payload)
    if enabled is not True:
        return result
    if auto_oco_verified is not True or signed_ticks_reviewed is not True:
        raise ValueError("Auto OCO account mode and signed TP offsets are not independently verified")
    if type(verified_ticks) is not int or verified_ticks == 0 or "stopLossBracket" not in result:
        raise ValueError("Explicit reviewed nonzero TP ticks and existing stop bracket required")
    result["takeProfitBracket"] = dict(ticks=verified_ticks, type=1)
    return result


def broker_transport(*args, **kwargs):
    raise ValueError("Trade-manager broker amendments/partial exits are disabled pending verified linked-order reconciliation")


def initialize(conn):
    if conn.in_transaction:
        raise ValueError("Exit schema requires an idle connection")
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS trade_exit_intents (
      id TEXT PRIMARY KEY, account TEXT NOT NULL, trade_id TEXT NOT NULL,
      status TEXT NOT NULL, record TEXT NOT NULL);
    CREATE UNIQUE INDEX IF NOT EXISTS trade_one_active_exit ON trade_exit_intents(account,trade_id)
      WHERE status IN ('INTENT','UNKNOWN','PARTIAL','AWAITING_PROTECTION');
    CREATE TABLE IF NOT EXISTS trade_exit_audit (
      id INTEGER PRIMARY KEY AUTOINCREMENT, intent TEXT NOT NULL, record TEXT NOT NULL);
    """)


def reserve_exit(conn, *, account, trade_id, contract_id, quantity, position_quantity, parent_order_id, direction, reason):
    initialize(conn)
    if not account or not trade_id or not contract_id or not parent_order_id or direction not in ("LONG", "SHORT"):
        raise ValueError("Explicit exact-account ownership required")
    if type(quantity) is not int or type(position_quantity) is not int or not 1 <= quantity <= position_quantity:
        raise ValueError("Exit cannot exceed reconciled whole-contract position")
    record = dict(account=account, trade_id=trade_id, contract_id=contract_id, quantity=quantity,
                  original_quantity=position_quantity, parent_order_id=parent_order_id, direction=direction,
                  reason=reason, status="INTENT", broker_order_id=None, transport="DISABLED / MOCK ONLY")
    identifier = digest(record)
    conn.execute("BEGIN IMMEDIATE")
    try:
        if conn.execute("SELECT 1 FROM trade_exit_intents WHERE id=?", (identifier,)).fetchone():
            conn.rollback()
            return None
        conn.execute("INSERT INTO trade_exit_intents VALUES (?,?,?,?,?)", (identifier, str(account), trade_id, "INTENT", frozen_json(record)))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return identifier


def reconcile_exit(conn, identifier, *, account, position, orders, snapshot_at, now, response=None):
    """A response alone never proves safe flat/protected state; no automatic retry."""
    if not 0 <= (stamp(now)-stamp(snapshot_at)).total_seconds() <= 10:
        raise ValueError("Fresh broker reconciliation snapshot required")
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT record FROM trade_exit_intents WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise ValueError("Unknown exit intent")
        record = json.loads(row[0])
        if record["account"] != account:
            raise ValueError("Exit reconciliation account mismatch")
        if record["status"] in ("CLOSED", "CONFIRMED", "REJECTED"):
            conn.rollback()
            return record
        if not isinstance(orders, list) or any(order.get("accountId") != account for order in orders):
            raise ValueError("Fresh exact-account working orders required")
        relevant = [order for order in orders if order.get("contractId") == record["contract_id"]]
        if position is None:
            status = "CLOSED" if not relevant else "AWAITING_PROTECTION"
        else:
            if (position.get("accountId") != account or position.get("contractId") != record["contract_id"]
                    or type(position.get("size")) is not int or not 1 <= position["size"] <= record["original_quantity"]
                    or position.get("type") != (1 if record["direction"] == "LONG" else 2)):
                raise ValueError("Unexpected or reversed broker position; manual review")
            remaining = position["size"]
            protected = len(relevant) == 1 and all(order.get("type") == 4 and order.get("size") == remaining and order.get("side") == (1 if record["direction"] == "LONG" else 0)
                            and order.get("parentOrderId") == record["parent_order_id"] and finite(order.get("stopPrice")) and order["stopPrice"] > 0 for order in relevant)
            expected = record["original_quantity"]-record["quantity"]
            status = "AWAITING_PROTECTION" if not protected else "CONFIRMED" if remaining == expected else "PARTIAL" if expected < remaining < record["original_quantity"] else "UNKNOWN"
            if response and response.get("success") is False and response.get("errorCode") not in (7, 8) and remaining == record["original_quantity"] and protected:
                status = "REJECTED"
        record.update(status=status, new_entries_blocked=status not in ("CLOSED", "CONFIRMED", "REJECTED"))
        conn.execute("UPDATE trade_exit_intents SET status=?,record=? WHERE id=?", (status, frozen_json(record), identifier))
        conn.execute("INSERT INTO trade_exit_audit(intent,record) VALUES (?,?)", (identifier, frozen_json(record)))
        conn.commit()
        return record
    except BaseException:
        conn.rollback()
        raise
