"""Account-isolated micro executor; target fixed for the lifetime of its process."""
import json
import math
import time
import requests
from contextlib import closing
from datetime import datetime, timezone
from threading import Event

from live_store import connect
from live_accounts import quantities_for, copy_role
from projectx_client import post, login
from signal_lifecycle import alert_history
from bot_monitor import read_status
from market_session import market_session
import practice_safety
import bot_audit
import bot_controls
import bot_health
from execution_target import PROFILE, TARGET, assert_other_idle

ACCOUNT_ID = TARGET["id"]
ACCOUNT_NAME = TARGET["name"]
MICROS = {"NQ=F": ("MNQ", "F.US.MNQ", .25, 2), "ES=F": ("MES", "F.US.MES", .25, 5), "YM=F": ("MYM", "F.US.MYM", 1, .5)}
# Minimum confirmed by the Practice broker's MYM rejection.
MIN_STOP_TICKS = {"MYM": 4}
COOLDOWN_SECONDS = 300


def db():
    conn = connect()
    conn.execute(f"CREATE TABLE IF NOT EXISTS {PROFILE}_control (id INTEGER PRIMARY KEY, settings TEXT, status TEXT)")
    conn.execute(f"INSERT OR IGNORE INTO {PROFILE}_control VALUES (1,'{{}}','{{}}')")
    conn.execute(f"CREATE TABLE IF NOT EXISTS {PROFILE}_jobs (alert_id INTEGER PRIMARY KEY, record TEXT NOT NULL)")
    conn.execute(f"CREATE TABLE IF NOT EXISTS {PROFILE}_job_events (id INTEGER PRIMARY KEY, alert_id INTEGER, recorded_at TEXT, record TEXT NOT NULL)")
    conn.commit()
    return conn


def snapshot():
    with closing(db()) as conn:
        row = conn.execute(f"SELECT settings,status FROM {PROFILE}_control WHERE id=1").fetchone()
        jobs = [json.loads(r[0]) for r in conn.execute(f"SELECT record FROM {PROFILE}_jobs ORDER BY alert_id DESC")]
    return json.loads(row[0]), json.loads(row[1]), jobs


def control(settings):
    with closing(db()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        if settings.get("enabled"):
            assert_other_idle(conn)
        conn.execute(f"UPDATE {PROFILE}_control SET settings=? WHERE id=1", (json.dumps(settings),))
        conn.commit()


def status(message):
    if PROFILE == "leader":
        message = message.replace("Practice", "Leader")
    with closing(db()) as conn:
        conn.execute(f"UPDATE {PROFILE}_control SET status=? WHERE id=1", (json.dumps(dict(message=message, version="accounts-v1", recovery="reconnect-v1", entry_policy="multi-symbol-v1", account_id=ACCOUNT_ID, updated_at=datetime.now(timezone.utc).isoformat())),))
        detail = "Post-trade cooldown active" if message.startswith("Post-trade cooldown") else message
        critical = any(word in message.lower() for word in ("error", "uncertain", "unconfirmed", "rejected", "manual", "loss lock"))
        bot_audit.emit("executor", "Execution status", detail, severity="warning" if critical else "info", notify=critical, conn=conn)
        conn.commit()


def save_job(job):
    with closing(db()) as conn:
        job["account_id"] = ACCOUNT_ID
        previous = conn.execute(f"SELECT record FROM {PROFILE}_jobs WHERE alert_id=?", (job["alert_id"],)).fetchone()
        old = json.loads(previous[0]) if previous else {}
        for field, label in (("state", "Order state"), ("fill_price", "Broker fill"), ("protected", "Broker stop verification")):
            if field in job and old.get(field) != job[field]:
                detail = f"{label}: {job[field]} / {job.get('symbol', '')} / order {job.get('order_id', '--')}"
                if field == "state":
                    detail += " / " + str(job.get("close_reason") or job.get("error_message") or "")
                bot_audit.emit(f"job:{job['alert_id']}:{field}", label, detail, job["alert_id"],
                               severity="warning" if job.get("state") in ("Rejected", "Unknown") or (field == "protected" and not job[field]) else "info",
                               notify=field in ("state", "fill_price") or not job.get("protected", True), conn=conn)
        if previous is None or json.loads(previous[0]).get("state") != job["state"]:
            job["state_updated_at"] = datetime.now(timezone.utc).isoformat()
            conn.execute(f"INSERT INTO {PROFILE}_job_events (alert_id,recorded_at,record) VALUES (?,?,?)",
                         (job["alert_id"], job["state_updated_at"], json.dumps(job)))
        conn.execute(f"UPDATE {PROFILE}_jobs SET record=? WHERE alert_id=?", (json.dumps(job), job["alert_id"]))
        conn.commit()


def claim(job):
    with closing(db()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        assert_other_idle(conn)
        active = [json.loads(row[0]) for row in conn.execute(f"SELECT record FROM {PROFILE}_jobs")]
        active = [j for j in active if j["state"] not in ("Closed", "Rejected")]
        if active:
            if (len(active) >= 3 or job.get("quantity") != 1
                    or job.get("symbol") not in ("MNQ", "MES", "MYM")):
                return False
            if any(other["state"] != "Open" or not other.get("protected")
                   or other.get("symbol") == job.get("symbol")
                   or other.get("contract_id") == job.get("contract_id")
                   or other.get("side") != job.get("side") for other in active):
                return False
        job["account_id"] = ACCOUNT_ID
        inserted = conn.execute(f"INSERT OR IGNORE INTO {PROFILE}_jobs VALUES (?,?)", (job["alert_id"], json.dumps(job))).rowcount
        if inserted:
            bot_audit.emit(f"job:{job['alert_id']}:intent", "Entry intent", f"{job.get('quantity')} {job.get('symbol')} / signal {job.get('signal_entry')}", job["alert_id"], conn=conn)
        conn.commit()
        return bool(inserted)


def call(path, payload, token):
    data = post(path, payload, token=token)
    if data.get("success") is not True:
        raise RuntimeError(f"API rejected {path}; code {data.get('errorCode')}")
    return data


def verify_account(token):
    accounts = call("/api/Account/search", {"onlyActiveAccounts": False}, token)["accounts"]
    account = next((a for a in accounts if a.get("id") == ACCOUNT_ID), {})
    if (account.get("name") != ACCOUNT_NAME or account.get("simulated") is not True
            or account.get("canTrade") is not True or copy_role(account) != TARGET["role"]):
        raise RuntimeError("Execution account identity or eligibility check failed")
    return account


def account_state(token):
    payload = {"accountId": ACCOUNT_ID}
    return (call("/api/Position/searchOpen", payload, token)["positions"],
            call("/api/Order/searchOpen", payload, token)["orders"])


def quote_fresh(result, now):
    try:
        quote = datetime.fromisoformat(result["quote_time"])
        updated = datetime.fromisoformat(result["updated_at"])
        return result.get("feed_fresh") and 0 <= (now-quote).total_seconds() <= 10 and 0 <= (now-updated).total_seconds() <= 10
    except (KeyError, TypeError, ValueError):
        return False


def arm(max_trade_loss, max_run_loss, confirmed, quantities=None, acknowledge_loss=False, enable_mym=False):
    if confirmed is not True:
        raise ValueError("Confirm isolated Practice account and Auto OCO Brackets")
    if not all(math.isfinite(float(v)) and float(v) > 0 for v in (max_trade_loss, max_run_loss)):
        raise ValueError("Positive loss limits are required")
    quantities = quantities or quantities_for(ACCOUNT_ID)
    if set(quantities) != {"MNQ", "MES", "MYM"} or any(type(v) is not int or not 1 <= v <= 4 for v in quantities.values()):
        raise ValueError("Micro quantities must be 1-4")
    token = login()
    account = verify_account(token)
    gate = practice_safety.check(account["balance"], snapshot()[0].get("start_balance"), account_id=TARGET["gate_id"])
    if gate["locked"] and not acknowledge_loss:
        raise ValueError("$500 account loss lock. Explicit loss-reset confirmation required.")
    positions, orders = account_state(token)
    _, _, jobs = snapshot()
    if positions or orders or any(j["state"] not in ("Closed", "Rejected") for j in jobs):
        raise ValueError("Practice must be flat with no orders or unresolved executor jobs")
    if gate["locked"]:
        practice_safety.check(account["balance"], acknowledge=True, account_id=TARGET["gate_id"])
    control(dict(enabled=True, after_id=max([r["id"] for r in alert_history(10000)] or [0]),
                 max_trade_loss=float(max_trade_loss), max_run_loss=float(max_run_loss),
                 start_balance=float(account["balance"]), quantities=quantities, enable_mym=enable_mym is True))
    status("Armed for new signals only")


def pause():
    update_settings(enabled=False)


def update_settings(**changes):
    with closing(db()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        settings = json.loads(conn.execute(f"SELECT settings FROM {PROFILE}_control WHERE id=1").fetchone()[0])
        settings.update(changes)
        conn.execute(f"UPDATE {PROFILE}_control SET settings=? WHERE id=1", (json.dumps(settings),))
        conn.commit()


def configure(quantities, enable_mym):
    if set(quantities) != {"MNQ", "MES", "MYM"} or any(type(v) is not int or not 1 <= v <= 4 for v in quantities.values()):
        raise ValueError("Micro quantities must be 1-4")
    update_settings(quantities=quantities, enable_mym=enable_mym is True)
    bot_audit.emit("sizing", "Sizing updated", str(quantities))


def request_emergency_close(confirmed):
    if confirmed is not True:
        raise ValueError("Confirm closing the bot-owned Practice position")
    update_settings(enabled=False, emergency_close=True)
    bot_audit.emit("emergency", "Close requested", "New entries paused. Awaiting worker confirmation of bot-owned Practice position.", severity="warning", notify=True)


def symbol_enabled(symbol, settings):
    return symbol in ("NQ=F", "ES=F") or (symbol == "YM=F" and settings.get("enable_mym") is True)


def set_mym_enabled(enabled):
    if type(enabled) is not bool:
        raise ValueError("MYM activation must be true or false")
    with closing(db()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        settings = json.loads(conn.execute(f"SELECT settings FROM {PROFILE}_control WHERE id=1").fetchone()[0])
        settings["enable_mym"] = enabled
        conn.execute(f"UPDATE {PROFILE}_control SET settings=? WHERE id=1", (json.dumps(settings),))
        conn.commit()


def build_order(signal, contract, quantity, max_loss=None):
    micro, symbol_id, tick_size, point_value = MICROS[signal["symbol"]]
    if contract.get("symbolId") != symbol_id or contract.get("activeContract") is not True:
        raise ValueError("Not the active micro contract")
    if not str(contract.get("id", "")).startswith("CON.F.US." + micro + "."):
        raise ValueError("Contract ID is not an approved micro")
    if type(quantity) is not int or not 1 <= quantity <= 4 or signal.get("signal") not in ("LONG", "SHORT"):
        raise ValueError("Invalid direction or quantity")
    entry, stop = float(signal["entry"]), float(signal.get("initial_stop", signal["stop"]))
    risk = (entry - stop) * (1 if signal["signal"] == "LONG" else -1)
    if not math.isfinite(risk) or risk <= 0:
        raise ValueError("Invalid protective stop")
    ticks = math.ceil(risk / tick_size)
    minimum = MIN_STOP_TICKS.get(micro, 1)
    if ticks < minimum:
        raise ValueError(f"{micro} stop is {ticks} ticks; broker minimum is {minimum}. Setup skipped.")
    if max_loss is not None:
        quantity = min(quantity, math.floor(max_loss / (ticks * tick_size * point_value)))
    if quantity < 1:
        raise ValueError("Initial stop risk exceeds the per-trade limit")
    return dict(accountId=ACCOUNT_ID, contractId=contract["id"], type=2,
                side=0 if signal["signal"] == "LONG" else 1, size=quantity,
                customTag=f"gx-{PROFILE}-{signal['id']}",
                stopLossBracket=dict(ticks=-ticks if signal["signal"] == "LONG" else ticks, type=4))


def close_job(job, token):
    # Persist intent before transmission. Ambiguous responses are never retried.
    job["state"] = "Closing"
    save_job(job)
    verify_account(token)
    call("/api/Position/closeContract", {"accountId": ACCOUNT_ID, "contractId": job["contract_id"]}, token)


def record_fill(job, position):
    value = position.get("averagePrice")
    if value is None or not math.isfinite(float(value)) or float(value) <= 0:
        raise ValueError("Broker fill price unavailable")
    job.update(fill_price=float(value), filled_quantity=position["size"],
               fill_checked_at=datetime.now(timezone.utc).isoformat())
    job.setdefault("first_fill_observed_at", job["fill_checked_at"])
    if job.get("signal_entry") is not None:
        job["slippage_points"] = (float(value)-job["signal_entry"]) * (1 if job["side"] == 0 else -1)
    save_job(job)


def opposing_exposure(side, positions, orders, jobs):
    if any(p.get("type") != side + 1 for p in positions):
        return True
    active = [j for j in jobs if j["state"] not in ("Closed", "Rejected")]
    if any(j.get("side") != side for j in active):
        return True
    for order in orders:
        # Exit brackets are not new short/long entries. Require proven ownership.
        protective = any(
            j.get("order_id") is not None and order.get("parentOrderId") == j["order_id"]
            and order.get("contractId") == j["contract_id"] and order.get("type") == 4
            and order.get("side") == 1-j.get("side", -2)
            and order.get("size") == j.get("quantity") for j in active)
        if not protective and order.get("side") != side:
            return True
    return False


def protective_order(order, job):
    return (job.get("order_id") is not None and order.get("parentOrderId") == job["order_id"]
            and order.get("contractId") == job.get("contract_id") and order.get("type") == 4
            and order.get("side") == 1-job.get("side", -2) and order.get("size") == job.get("quantity"))


def entry_quantity(requested, positions, jobs, own_alert=None):
    occupied = positions or any(j["state"] not in ("Closed", "Rejected") and j["alert_id"] != own_alert for j in jobs)
    return min(requested, 1) if occupied else requested


def entry_wait(positions, orders, jobs, now=None, own_alert=None, cooldown_seconds=COOLDOWN_SECONDS, symbol=None):
    active = [j for j in jobs if j["state"] not in ("Closed", "Rejected") and j["alert_id"] != own_alert]
    if any(j["state"] != "Open" for j in active):
        return "Pending or unresolved order: waiting for broker reconciliation"
    if any(j.get("symbol") not in ("MNQ", "MES", "MYM") for j in active):
        return "Unrecognized position ownership: review required"
    if len({j.get("symbol") for j in active}) != len(active):
        return "Duplicate symbol exposure: review required"
    for position in positions:
        owners = [j for j in active if j.get("contract_id") == position.get("contractId")]
        if (len(owners) != 1 or position.get("size") != owners[0].get("quantity")
                or position.get("type") != owners[0].get("side", -2)+1):
            return "Unowned or mismatched broker position: review required"
    if len(positions) != len(active):
        return "Position close or fill awaiting broker reconciliation"
    if any(not any(protective_order(order, j) for j in active) for order in orders):
        return "Unrecognized working order: waiting for broker reconciliation"
    if any(not any(protective_order(order, j) for order in orders) for j in active):
        return "Protective stop not verified: additional entries blocked"
    if symbol and any(j["symbol"] == symbol for j in active):
        return f"{symbol} already has an open trade; no additional entry on the same symbol"
    if len(active) >= 3:
        return "All three symbol positions are occupied"
    now = time.time() if now is None else now
    closed = [datetime.fromisoformat(j["closed_confirmed_at"]).timestamp()
              for j in jobs if j["state"] == "Closed" and j.get("closed_confirmed_at")]
    remaining = math.ceil(max(closed, default=0) + cooldown_seconds - now)
    if remaining > 0:
        return f"Post-trade cooldown: {remaining // 60}:{remaining % 60:02d} remaining"
    return None


def cleanup_stop(job, token):
    """Cancel only this job's bracket after a fresh flat-position check."""
    verify_account(token)
    positions, orders = account_state(token)
    if any(p["contractId"] == job["contract_id"] for p in positions):
        return False
    current = [o for o in orders if o["contractId"] == job["contract_id"]]
    for order in current:
        if (order.get("parentOrderId") != job.get("order_id") or not job.get("order_id")
                or order.get("type") != 4 or order.get("side") != 1-job["side"]
                or order.get("size") != job["quantity"]):
            return False
    for order in current:
        key = str(order["id"])
        if key in job.get("cleanup_requested", []):
            return False
        job.setdefault("cleanup_requested", []).append(key)
        save_job(job)
        call("/api/Order/cancel", {"accountId": ACCOUNT_ID, "orderId": order["id"]}, token)
    return True


def cycle(token):
    settings, _, jobs = snapshot()
    unresolved = [j for j in jobs if j["state"] not in ("Closed", "Rejected")]
    account = verify_account(token)
    gate = practice_safety.check(account["balance"], settings.get("start_balance"), account_id=TARGET["gate_id"])
    if gate["locked"]:
        pause()
    positions, orders = account_state(token)
    bot_audit.emit("connection", "Broker connected", "Practice positions and orders reconciled", notify=True)
    bot_health.record(positions, orders)
    history = {r["id"]: r for r in alert_history(10000)}
    for job in unresolved:
        position = next((p for p in positions if p["contractId"] == job["contract_id"]), None)
        working = [o for o in orders if o["contractId"] == job["contract_id"]]
        if job["state"] in ("Intent", "Unknown"):
            pause()
            status("Uncertain submission: review Practice orders manually; no automatic retry")
            continue
        if position:
            if position.get("size") != job["quantity"] or position.get("type") != job["side"] + 1:
                pause()
                status("Unexpected Practice position: paused for manual review")
                continue
            signal = history.get(job["alert_id"])
            if signal and job.get("signal_entry") is None:
                job["signal_entry"] = signal.get("entry")
            record_fill(job, position)
            if job["state"] == "Closing":
                if time.time() - job.get("close_time", job["sent_at"]) > 30:
                    pause()
                    status("Close not confirmed: review Practice manually")
                continue
            protected = any(o.get("type") == 4 and o.get("side") == 1-job["side"]
                            and o.get("size") == job["quantity"] and job.get("order_id") is not None
                            and o.get("parentOrderId") == job["order_id"] for o in working)
            signal = history.get(job["alert_id"])
            risk_stop = gate["locked"]
            if (not protected and time.time() - job["sent_at"] > 15) or (signal and signal["status"] == "Closed") or risk_stop or settings.get("emergency_close"):
                job["close_reason"] = ("User emergency close" if settings.get("emergency_close") else "$500 account loss lock" if risk_stop else "Missing verified broker stop" if not protected else signal.get("exit_reason", "Signal closed"))
                bot_audit.emit(f"job:{job['alert_id']}:exit", "Exit decision", job["close_reason"], job["alert_id"], severity="warning" if risk_stop or not protected else "info", notify=True)
                job["close_time"] = time.time()
                close_job(job, token)
                if risk_stop or not protected:
                    pause()
                status("Practice close submitted; awaiting flat position")
                continue
            job.update(state="Open", fill_price=position.get("averagePrice"), protected=protected)
            save_job(job)
        elif time.time() - job["sent_at"] > 30:
            if working:
                if job["state"] in ("Open", "Closing") and cleanup_stop(job, token):
                    status("Backup stop cleanup submitted; awaiting broker confirmation")
                    continue
                pause()
                status("Residual orders found: review Practice manually")
                continue
            if job["state"] == "Submitted" and job.get("fill_price") is None:
                job.update(state="Unknown", error_message="Order no longer open, but a fill was not observed. Broker review required.")
                save_job(job)
                pause()
                status("Unconfirmed order outcome: review broker fills; no automatic retry")
                continue
            job.update(state="Closed", closed_confirmed_at=datetime.now(timezone.utc).isoformat())
            save_job(job)
    settings, _, jobs = snapshot()
    if settings.get("emergency_close"):
        if not positions and not orders and not any(j["state"] not in ("Closed", "Rejected") for j in jobs):
            update_settings(emergency_close=False)
            bot_audit.emit("emergency", "Flat confirmed", "Practice has no open positions or orders.", notify=True)
        else:
            status("Emergency close pending: only bot-owned positions may be closed; review unowned or unresolved exposure manually")
            return
    if not settings.get("enabled"):
        status("New entries paused; existing positions still monitored")
        return
    if gate["locked"]:
        pause()
        status("$500 account loss lock: confirmation required")
        return
    if not market_session()["is_open"]:
        status("Waiting for market session")
        return
    waiting = entry_wait(positions, orders, jobs, cooldown_seconds=bot_controls.read()["cooldown_minutes"]*60)
    if waiting:
        status(waiting)
        seen = {j["alert_id"] for j in jobs}
        for signal in history.values():
            if signal["status"] == "Active" and signal["id"] > settings["after_id"] and signal["id"] not in seen and symbol_enabled(signal["symbol"], settings):
                bot_audit.emit(f"decision:{signal['id']}", "Entry blocked", waiting, signal["id"])
        return
    seen = {j["alert_id"] for j in jobs}
    results = read_status()
    for signal in sorted(history.values(), key=lambda r: r["id"]):
        if not symbol_enabled(signal["symbol"], settings):
            if signal["status"] == "Active":
                bot_audit.emit(f"decision:{signal['id']}", "Entry blocked", "Micro symbol not activated", signal["id"])
            continue
        if signal["id"] <= settings["after_id"] or signal["id"] in seen or signal["status"] != "Active" or signal["symbol"] not in MICROS:
            continue
        if not bot_controls.enabled(signal["symbol"], signal["strategy"]):
            bot_audit.emit(f"decision:{signal['id']}", "Entry blocked", "Symbol or strategy disabled for execution", signal["id"])
            continue
        entered = datetime.fromisoformat(signal.get("entry_time") or signal["observed_at"])
        age = (datetime.now(timezone.utc) - entered).total_seconds()
        result = results.get((signal["symbol"], signal["strategy"]), {})
        if not 0 <= age <= 15 or not quote_fresh(result, datetime.now(timezone.utc)):
            bot_audit.emit(f"decision:{signal['id']}", "Entry blocked", "Signal expired or feed/monitor stale", signal["id"])
            continue
        # Conflicting active strategies on the same index do not produce an order.
        if any(r["status"] == "Active" and r["symbol"] == signal["symbol"] and r["signal"] != signal["signal"]
               and bot_controls.enabled(r["symbol"],r["strategy"]) for r in history.values()):
            bot_audit.emit(f"decision:{signal['id']}", "Entry blocked", "Conflicting active strategy direction", signal["id"])
            continue
        micro, symbol_id, _, _ = MICROS[signal["symbol"]]
        side = 0 if signal["signal"] == "LONG" else 1
        waiting = entry_wait(positions, orders, jobs, symbol=micro, cooldown_seconds=bot_controls.read()["cooldown_minutes"]*60)
        if waiting:
            bot_audit.emit(f"decision:{signal['id']}", "Entry blocked", waiting, signal["id"])
            continue
        if opposing_exposure(side, positions, orders, jobs):
            status("Opposing entry blocked: wait for existing exposure to close")
            bot_audit.emit(f"decision:{signal['id']}", "Entry blocked", "Opposing account exposure; existing direction must close first", signal["id"])
            continue
        contracts = call("/api/Contract/search", {"searchText": micro, "live": False}, token)["contracts"]
        matches = [c for c in contracts if c.get("symbolId") == symbol_id and c.get("activeContract") is True]
        if len(matches) != 1:
            raise RuntimeError("Active micro contract could not be uniquely resolved")
        contract = matches[0]
        if any(p["contractId"] == contract["id"] for p in positions) or any(o["contractId"] == contract["id"] for o in orders):
            continue
        try:
            payload = build_order(signal, contract, entry_quantity(settings["quantities"][micro], positions, jobs))
        except ValueError as error:
            status(f"Signal skipped: {error}")
            continue
        job = dict(alert_id=signal["id"], symbol=micro, contract_id=contract["id"], quantity=payload["size"],
                   signal_entry=signal["entry"],
                   requested_quantity=settings["quantities"][micro], stop_ticks=abs(payload["stopLossBracket"]["ticks"]),
                   sizing_reason="Additional symbol: capped at 1 contract" if positions else "First position: selected quantity",
                   side=payload["side"], state="Intent", sent_at=time.time(), tag=payload["customTag"])
        if not claim(job):
            continue
        try:
            verify_account(token)
            if not symbol_enabled(signal["symbol"], snapshot()[0]) or not bot_controls.enabled(signal["symbol"], signal["strategy"]):
                job.update(state="Rejected", error_message="Not submitted: symbol disabled")
                save_job(job)
                return
            fresh_positions, fresh_orders = account_state(token)
            fresh_jobs = snapshot()[2]
            waiting = entry_wait(fresh_positions, fresh_orders, fresh_jobs, own_alert=job["alert_id"], symbol=micro, cooldown_seconds=bot_controls.read()["cooldown_minutes"]*60)
            if waiting:
                job.update(state="Rejected", error_message=f"Not submitted: {waiting}")
                save_job(job)
                return
            fresh_size = entry_quantity(settings["quantities"][micro], fresh_positions, fresh_jobs, own_alert=job["alert_id"])
            if payload["size"] > fresh_size:
                job.update(state="Rejected", error_message="Not submitted: account exposure changed sizing during preflight")
                save_job(job)
                return
            if opposing_exposure(payload["side"], fresh_positions, fresh_orders, snapshot()[2]):
                job.update(state="Rejected", error_message="Not submitted: opposing account exposure")
                save_job(job)
                return
            if not snapshot()[0].get("enabled"):
                job["state"] = "Rejected"
                save_job(job)
                return
            # Network lookups may have consumed the signal's short entry window.
            latest = read_status().get((signal["symbol"], signal["strategy"]), {})
            now = datetime.now(timezone.utc)
            current_signal = next((r for r in alert_history(10000) if r["id"] == signal["id"]), {})
            if not quote_fresh(latest, now) or not 0 <= (now-entered).total_seconds() <= 15 or current_signal.get("status") != "Active" or not market_session()["is_open"]:
                job.update(state="Rejected", error_message="Not submitted: signal or quote freshness changed during preflight")
                save_job(job)
                return
            response = post("/api/Order/place", payload, token=token)
            job.update(state="Submitted" if response.get("success") is True else "Rejected",
                       order_id=response.get("orderId"), error_code=response.get("errorCode"),
                       error_message=str(response.get("errorMessage") or "")[:500])
            save_job(job)
            if job["state"] == "Rejected":
                pause()
                status("Entry rejected. See broker reason in order history; no automatic retry.")
                return
        except Exception:
            job["state"] = "Unknown"
            save_job(job)
            pause()
            raise
        status("Practice entry submitted with protective bracket")
        return
    status("Monitoring Practice positions and new signals")


def recover_connection(error):
    retryable = isinstance(error, (requests.Timeout, requests.ConnectionError)) or (
        isinstance(error, requests.HTTPError) and error.response is not None
        and (error.response.status_code in (401, 408, 429) or error.response.status_code >= 500))
    # Never re-enable here: manual pause and uncertain-submission locks win.
    if retryable:
        bot_audit.emit("connection", "Broker reconnecting", "Temporary API failure; retrying connection. Run/Pause selection preserved; no entries until broker checks succeed.", severity="warning", notify=True)
        status("Broker reconnecting; waiting for successful account reconciliation")
    else:
        pause()
        bot_audit.emit("connection", "Broker unavailable", "Non-transient error; entries paused. Manual account review required.", severity="critical", notify=True)
        status("Practice API error: new entries paused; inspect account before resuming")
    return retryable


def run_practice():
    token, authenticated = None, 0
    failures = 0
    while True:
        settings, jobs = {}, []
        try:
            settings, _, jobs = snapshot()
            if token is None or time.time() - authenticated > 3600:
                token, authenticated = login(), time.time()
            cycle(token)
            failures = 0
        except Exception as error:
            recover_connection(error)
            failures += 1
            token = None
        Event().wait(min(30, 3 * 2 ** min(failures-1, 4)) if failures else 3 if settings.get("enabled") or settings.get("emergency_close") or any(j["state"] not in ("Closed", "Rejected") for j in jobs) else 15)
