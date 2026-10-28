"""Account-isolated micro executor; target fixed for the lifetime of its process."""
import json
import math
import time
import requests
import sqlite3
import logging
from contextlib import closing
from datetime import datetime, timezone
from threading import Event

from goxtrade.data.live_store import connect
from goxtrade.execution.live_accounts import quantities_for, copy_role
from goxtrade.execution.projectx_client import post, login
from goxtrade.bot.signal_lifecycle import alert_history
from goxtrade.bot.bot_monitor import read_status
from goxtrade.market.market_session import market_session
from goxtrade.execution import practice_safety
from goxtrade.bot import bot_audit
from goxtrade.bot import bot_controls
from goxtrade.strategies import overnight_policy
from goxtrade.strategies import volatility_guard
from goxtrade.strategies import entry_confirmation
from goxtrade.bot import bot_health
from goxtrade.config.execution_identity import PROFILE, TARGET, assert_other_idle, assert_current
from goxtrade.strategies.strategy_catalog import order_block as execution_block, crossover_key
from goxtrade.execution.practice_automation import session_settings, job_session
from goxtrade.execution import safeguards
from goxtrade.runtime.build_identity import fingerprint

WORKER_BUILD = fingerprint()
SCHEDULING_MODE = "watchdog"

ACCOUNT_ID = TARGET["id"]
ACCOUNT_NAME = TARGET["name"]
MICROS = {"NQ=F": ("MNQ", "F.US.MNQ", .25, 2), "ES=F": ("MES", "F.US.MES", .25, 5), "YM=F": ("MYM", "F.US.MYM", 1, .5)}
# Minimum confirmed by the Practice broker's MYM rejection.
MIN_STOP_TICKS = {"MYM": 4}
COOLDOWN_SECONDS = 300


def db():
    conn = connect()
    safeguards.initialize(conn)
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


def control(settings, expected_settings=None):
    if settings.get("enabled"):
        assert_current()
    with closing(db()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        if expected_settings is not None:
            current=json.loads(conn.execute(f"SELECT settings FROM {PROFILE}_control WHERE id=1").fetchone()[0])
            if current!=expected_settings:
                raise ValueError("Execution settings changed during authorization; review and start again")
        if settings.get("enabled"):
            assert_other_idle(conn)
        conn.execute(f"UPDATE {PROFILE}_control SET settings=? WHERE id=1", (json.dumps(settings),))
        conn.commit()


def status(message):
    if PROFILE == "leader":
        message = message.replace("Practice", "Leader")
    with closing(db()) as conn:
        conn.execute(f"UPDATE {PROFILE}_control SET status=? WHERE id=1", (json.dumps(dict(message=message, version="accounts-v1", recovery="reconnect-v1", entry_policy="multi-symbol-v1", practice_automation=PROFILE=="practice", safeguards_version=safeguards.PROTOCOL_VERSION, worker_build=WORKER_BUILD, scheduler=SCHEDULING_MODE, account_id=ACCOUNT_ID, updated_at=datetime.now(timezone.utc).isoformat())),))
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


def retryable_preflight(job):
    """Only durable Practice aborts before the transport boundary may retry."""
    return (PROFILE == "practice" and job.get("account_profile") == "practice"
            and job.get("account_id") == ACCOUNT_ID and job.get("state") == "Rejected"
            and job.get("submission_status") == "NOT_SENT"
            and job.get("error_code") in (None, 0)
            and all(job.get(key) is None for key in ("order_id", "fill_price", "filled_quantity",
                                                    "first_fill_observed_at", "closed_confirmed_at")))


def claim(job):
    assert_current()
    if execution_block(job, PROFILE):
        return False
    with closing(db()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        assert_other_idle(conn)
        current_settings=json.loads(conn.execute(f"SELECT settings FROM {PROFILE}_control WHERE id=1").fetchone()[0])
        session_id=session_settings(current_settings).get("id")
        if session_id or job_session(job):
            if not current_settings.get("enabled") or session_id != job_session(job) or PROFILE != "practice":
                return False
        previous = conn.execute(f"SELECT record FROM {PROFILE}_jobs WHERE alert_id=?", (job["alert_id"],)).fetchone()
        retrying = previous is not None and retryable_preflight(json.loads(previous[0]))
        if previous:
            old = json.loads(previous[0])
            identity_fields = ("symbol", "contract_id", "side", "strategy", "strategy_id", "unique_setup_id",
                               "config_fingerprint", "crossover_key", "consumption_key", "automation_session",
                               "entry_mode", "signal_minutes", "source_contract", "candle_time", "session_id")
            if (not retrying or not current_settings.get("enabled") or job.get("state") != "Intent"
                    or any(old.get(key) != job.get(key) for key in identity_fields)):
                return False
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='bot_alert_history'").fetchone():
            signal = conn.execute("SELECT record FROM bot_alert_history WHERE id=?",(job["alert_id"],)).fetchone()
            if signal:
                stored = json.loads(signal[0])
                if stored.get("status") != "Active" or execution_block(stored, PROFILE):
                    return False
                if stored.get("strategy_id") in ("vwap_ema_cross","previous_day_box") and any(job.get(key) != stored.get(key)
                        for key in ("strategy_id", "strategy", "unique_setup_id", "config_fingerprint", "entry_mode", "signal_minutes", "consumption_key")):
                    return False
        event = job.get("consumption_key") or job.get("crossover_key") or job.get("unique_setup_id")
        if event:
            conn.execute(f"CREATE TABLE IF NOT EXISTS {PROFILE}_entry_events (setup_id TEXT PRIMARY KEY,alert_id INTEGER NOT NULL)")
            consumed = conn.execute(f"SELECT alert_id FROM {PROFILE}_entry_events WHERE setup_id=?", (event,)).fetchone()
            if consumed and not (retrying and consumed[0] == job["alert_id"]):
                return False
        active = [json.loads(row[0]) for row in conn.execute(f"SELECT record FROM {PROFILE}_jobs")]
        if job.get("strategy_id")=="previous_day_box":
            from goxtrade.strategies.previous_day_box_config import PreviousDayBoxConfig
            frozen = PreviousDayBoxConfig.from_dict(job.get("config_snapshot"))
            same = [old for old in active if old.get("strategy_id")=="previous_day_box" and old.get("source_contract")==job.get("source_contract") and old.get("state")!="Rejected"]
            count = sum(old.get("session_id")==job.get("session_id") for old in same)
            if frozen.max_entries_per_box and count>=frozen.max_entries_per_box:
                return False
            closes = [datetime.fromisoformat(old["closed_confirmed_at"]).timestamp() for old in same if old.get("closed_confirmed_at")]
            if closes and time.time()<max(closes)+frozen.cooldown_minutes*60:
                return False
        if event:
            for old in active:
                if retrying and old["alert_id"] == job["alert_id"]:
                    continue
                if old.get("unique_setup_id") == job.get("unique_setup_id") or old.get("crossover_key") == event:
                    return False
                if conn.execute("SELECT 1 FROM sqlite_master WHERE name='bot_alert_history'").fetchone():
                    saved = conn.execute("SELECT record FROM bot_alert_history WHERE id=?", (old["alert_id"],)).fetchone()
                    if saved and crossover_key(json.loads(saved[0])) == event:
                        return False
        active = [j for j in active if j["state"] not in ("Closed", "Rejected")]
        if overnight_policy.overnight() and (active or job.get('quantity',1)>overnight_policy.quantity(job.get('quantity',1),limits=safeguards.active(TARGET['gate_id'],conn))):
            return False
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
        if PROFILE == "practice" and job.get("state") == "Intent":
            job["submission_status"] = "NOT_SENT"
            job["attempt"] = json.loads(previous[0]).get("attempt", 1)+1 if retrying else 1
        if retrying:
            inserted = conn.execute(f"UPDATE {PROFILE}_jobs SET record=? WHERE alert_id=? AND record=?",
                                    (json.dumps(job), job["alert_id"], previous[0])).rowcount
            if inserted:
                conn.execute(f"INSERT INTO {PROFILE}_job_events (alert_id,recorded_at,record) VALUES (?,?,?)",
                             (job["alert_id"], datetime.now(timezone.utc).isoformat(), json.dumps(job)))
        else:
            inserted = conn.execute(f"INSERT OR IGNORE INTO {PROFILE}_jobs VALUES (?,?)", (job["alert_id"], json.dumps(job))).rowcount
        if inserted:
            if event:
                conn.execute(f"INSERT OR IGNORE INTO {PROFILE}_entry_events VALUES (?,?)", (event, job["alert_id"]))
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
    positions = call("/api/Position/searchOpen", payload, token).get("positions")
    orders = call("/api/Order/searchOpen", payload, token).get("orders")
    for collection in (positions, orders):
        if not isinstance(collection, list) or any(
                not isinstance(row, dict) or row.get("accountId", ACCOUNT_ID) != ACCOUNT_ID
                for row in collection):
            raise RuntimeError("Broker exposure response is incomplete or belongs to another account")
    return positions, orders


def quote_fresh(result, now):
    try:
        quote = datetime.fromisoformat(result["quote_time"])
        updated = datetime.fromisoformat(result["updated_at"])
        return result.get("feed_fresh") and 0 <= (now-quote).total_seconds() <= 10 and 0 <= (now-updated).total_seconds() <= 10
    except (KeyError, TypeError, ValueError):
        return False


def entry_window_history(history, now=None):
    # Active watch exits can outlive entry eligibility; they are not new exposure.
    if PROFILE != "practice":
        return list(history)
    now = now or datetime.now(timezone.utc)
    return [row for row in history if entry_confirmation.window_open(row, now, profile=PROFILE)]


def arm(max_trade_loss, max_run_loss, confirmed, quantities=None, acknowledge_loss=False, enable_mym=False, strategy_testing=None, automation=None, expected_settings=None):
    if PROFILE=="practice" and not (automation or strategy_testing):
        raise ValueError("Practice requires a manager-controlled automation session; legacy direct arming is disabled")
    assert_current()
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
        raise ValueError(f"Account loss lock ({gate.get('limit','configured')} USD). Explicit loss-reset confirmation required.")
    positions, orders = account_state(token)
    _, _, jobs = snapshot()
    if positions or orders or any(j["state"] not in ("Closed", "Rejected") for j in jobs):
        raise ValueError("Practice must be flat with no orders or unresolved executor jobs")
    if gate["locked"]:
        practice_safety.check(account["balance"], acknowledge=True, account_id=TARGET["gate_id"])
    session=automation or strategy_testing
    if session and (PROFILE != "practice" or session.get("account_id") != ACCOUNT_ID):
        raise ValueError("Automation requires the exact Practice account")
    control(dict(enabled=True, after_id=max([r["id"] for r in alert_history(10000)] or [0]),
                 max_trade_loss=float(max_trade_loss), max_run_loss=float(max_run_loss),
                 start_balance=float(account["balance"]), quantities=quantities, enable_mym=enable_mym is True,
                 **({"automation":automation} if automation else {"strategy_testing":strategy_testing} if strategy_testing else {})),expected_settings=expected_settings)
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
    if session_settings(settings):
        return PROFILE == "practice" and MICROS.get(symbol,(None,))[0] in session_settings(settings)["policy"]["symbols"]
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
    blocked = execution_block(signal, PROFILE)
    if blocked:
        raise ValueError(blocked)
    micro, symbol_id, tick_size, point_value = MICROS[signal["symbol"]]
    if contract.get("symbolId") != symbol_id or contract.get("activeContract") is not True:
        raise ValueError("Not the active micro contract")
    if not str(contract.get("id", "")).startswith("CON.F.US." + micro + "."):
        raise ValueError("Contract ID is not an approved micro")
    if signal.get("strategy_id") in ("vwap_ema_cross","previous_day_box") and str(signal.get("source_contract", "")).split(".")[-1] != contract["id"].split(".")[-1]:
        raise ValueError("Indicator reference and executable micro contract expiries do not match")
    if signal.get("strategy_id") == "previous_day_box":
        from goxtrade.strategies.previous_day_box import validate_entry
        from goxtrade.strategies.previous_day_box_config import PreviousDayBoxConfig
        blocked = validate_entry(signal,signal.get("entry"),datetime.now(timezone.utc))
        if blocked: raise ValueError(blocked)
        frozen = PreviousDayBoxConfig.from_dict(signal["config_snapshot"])
        risk = abs(signal["entry"]-signal["stop"])
        net_reward = abs(signal["target"]-signal["entry"])-2*frozen.estimated_commission_per_side/point_value-2*frozen.paper_slippage_ticks*tick_size
        if frozen.minimum_effective_rr and net_reward/risk<frozen.minimum_effective_rr:
            raise ValueError("Box minimum effective RR after estimated costs failed")
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


def check_order_safeguards(payload,gate,positions=(),orders=(),jobs=(),own_alert=None):
    limits=safeguards.active(TARGET['gate_id'])
    product=next((v for v in MICROS.values() if payload['contractId'].startswith('CON.F.US.'+v[0]+'.')),None)
    if product is None or payload['size']>limits.max_contracts:
        raise ValueError('Order exceeds the active account contract maximum')
    risk=abs(payload['stopLossBracket']['ticks'])*product[2]*product[3]*payload['size']
    open_risk=0.
    for position in positions:
        job=next((j for j in jobs if j.get('contract_id')==position.get('contractId') and j.get('state')=='Open'),None)
        stop=next((o for o in orders if job and protective_order(o,job)),None)
        if not job or not stop:
            raise ValueError('Cannot verify open stop risk for existing account exposure')
        specification=next((v for v in MICROS.values() if v[0]==job['symbol']),None)
        if not specification:
            raise ValueError('Unknown open instrument risk')
        distance=(position['averagePrice']-stop['stopPrice'])*(1 if job['side']==0 else -1)
        open_risk+=max(0,distance)*specification[3]*position['size']
    if risk+open_risk>limits.max_open_risk:
        raise ValueError('Order exceeds the active total open stop-risk budget')
    if gate.get('locked') or risk>min(limits.max_trade_risk,limits.loss_lock-max(0,gate.get('loss',0))):
        raise ValueError('Order exceeds active stop-risk or remaining account-loss budget')
    return risk


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
    price = order.get("stopPrice")
    tick = next((v[2] for v in MICROS.values() if v[0] == job.get("symbol")), None)
    if (type(price) not in (int, float) or not math.isfinite(price) or price <= 0
            or tick is None or abs(price/tick-round(price/tick)) > 1e-6
            or order.get("accountId", ACCOUNT_ID) != ACCOUNT_ID):
        return False
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
    from goxtrade.market.trading_schedule import execution_schedule
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
            protected = any(protective_order(o, job) for o in working)
            signal = history.get(job["alert_id"])
            risk_stop = gate["locked"]
            scheduled_exit = execution_schedule()["flatten"]
            invalid_box_fill = False
            if signal and job.get("strategy_id")=="previous_day_box":
                fill = job["fill_price"]
                original_stop = signal.get("initial_stop",signal["stop"])
                invalid_box_fill = not (original_stop<fill<signal["target"] if job["side"]==0 else signal["target"]<fill<original_stop)
            if (not protected and time.time() - job["sent_at"] > 15) or (signal and signal["status"] == "Closed") or risk_stop or settings.get("emergency_close") or scheduled_exit or invalid_box_fill:
                job["close_reason"] = ("Invalid box stop/target after actual broker fill" if invalid_box_fill else "User emergency close" if settings.get("emergency_close") else "Account loss lock" if risk_stop else "Scheduled 15:05 CT flatten" if scheduled_exit else "Missing verified broker stop" if not protected else signal.get("exit_reason", "Signal closed"))
                bot_audit.emit(f"job:{job['alert_id']}:exit", "Exit decision", job["close_reason"], job["alert_id"], severity="warning" if risk_stop or not protected else "info", notify=True)
                job["close_time"] = time.time()
                close_job(job, token)
                if risk_stop or not protected:
                    pause()
                status("Practice close submitted; awaiting flat position")
                continue
            job.update(state="Open", fill_price=position.get("averagePrice"), protected=protected)
            save_job(job)
        elif execution_schedule()["flatten"] and job["state"] == "Submitted" and any(o.get("id") == job.get("order_id") for o in working):
            # Cancel only the known entry; a racing fill is reconciled next cycle.
            if not job.get("session_cancel_requested"):
                job["session_cancel_requested"] = True
                save_job(job)
                call("/api/Order/cancel", {"accountId": ACCOUNT_ID,"orderId":job["order_id"]},token)
            status("Scheduled entry cancellation pending broker reconciliation")
            continue
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
    schedule = execution_schedule()
    from goxtrade.bot.watch_alerts import reconcile_closed_trades
    reconcile_closed_trades(PROFILE,ACCOUNT_ID)
    if not schedule["allow_entry"]:
        pending = bool(positions or orders or any(j["state"] not in ("Closed","Rejected") for j in jobs))
        message = schedule["reason"]
        if schedule["flatten"]:
            message += " / Exposure unresolved; verify broker" if pending else " / Broker flat confirmed"
            bot_audit.emit("session:flat", "Scheduled flatten",message,severity="warning" if pending else "info",notify=pending)
        status(message)
        for signal in history.values():
            if signal["status"] == "Active":
                bot_audit.emit(f"decision:{signal['id']}","Entry blocked",message,signal["id"])
        return
    if settings.get("emergency_close"):
        if not positions and not orders and not any(j["state"] not in ("Closed", "Rejected") for j in jobs):
            update_settings(emergency_close=False)
            bot_audit.emit("emergency", "Flat confirmed", "Practice has no open positions or orders.", notify=True)
        else:
            status("Emergency close pending: only bot-owned positions may be closed; review unowned or unresolved exposure manually")
            return
    if not settings.get("enabled"):
        status("New entries paused; existing positions still monitored")
        seen={job['alert_id'] for job in jobs}
        for signal in history.values():
            if (signal.get('status')=='Active' and signal['id']>(settings.get('after_id') or 0)
                    and signal['id'] not in seen and symbol_enabled(signal.get('symbol'),settings)):
                bot_audit.emit(f"decision:{signal['id']}","Entry blocked",
                               "New entries paused; existing positions still monitored",signal['id'])
        return
    if gate["locked"]:
        pause()
        status(f"Account loss lock ({gate.get('limit','configured')} USD): confirmation required")
        return
    if not market_session()["is_open"]:
        status("Waiting for market session")
        return
    waiting = entry_wait(positions, orders, jobs, cooldown_seconds=overnight_policy.cooldown_seconds(bot_controls.read()["cooldown_minutes"]*60))
    if waiting:
        status(waiting)
        seen = {j["alert_id"] for j in jobs if not retryable_preflight(j)}
        for signal in history.values():
            if signal["status"] == "Active" and signal["id"] > settings["after_id"] and signal["id"] not in seen and symbol_enabled(signal["symbol"], settings):
                bot_audit.emit(f"decision:{signal['id']}", "Entry blocked", waiting, signal["id"])
        return
    seen = {j["alert_id"] for j in jobs if not retryable_preflight(j)}
    results = read_status()
    manager_selected = None
    if session_settings(settings):
        from goxtrade.execution.practice_automation import selection
        manager_selected = selection(settings,history.values(),account,gate,positions,orders,jobs)
    for signal in sorted(history.values(), key=lambda r: r["id"]):
        if manager_selected is not None and signal["id"] not in manager_selected:
            continue
        permission_error = execution_block(signal, PROFILE)
        if permission_error:
            if signal.get("status") == "Active":
                bot_audit.emit(f"decision:{signal['id']}", "Entry blocked", permission_error, signal["id"])
            continue
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
        if not entry_confirmation.window_open(signal):
            bot_audit.emit(f"decision:{signal['id']}", "Entry blocked", "Setup entry window expired or not yet open", signal["id"])
            continue
        if not quote_fresh(result, datetime.now(timezone.utc)):
            bot_audit.emit(f"decision:{signal['id']}", "Entry blocked", "Feed or strategy monitor stale", signal["id"])
            continue
        confirmation = entry_confirmation.check(signal)
        if confirmation["state"] != "Confirmed":
            bot_audit.emit(f"decision:{signal['id']}", "Entry blocked", f"{confirmation['state']}: {confirmation['reason']}", signal["id"])
            continue
        # Conflicting active strategies on the same index do not produce an order.
        if any(r["status"] == "Active" and r["symbol"] == signal["symbol"] and r["signal"] != signal["signal"]
               and bot_controls.enabled(r["symbol"],r["strategy"]) for r in entry_window_history(history.values())):
            bot_audit.emit(f"decision:{signal['id']}", "Entry blocked", "Conflicting active strategy direction", signal["id"])
            continue
        micro, symbol_id, _, _ = MICROS[signal["symbol"]]
        side = 0 if signal["signal"] == "LONG" else 1
        waiting = entry_wait(positions, orders, jobs, symbol=micro, cooldown_seconds=overnight_policy.cooldown_seconds(bot_controls.read()["cooldown_minutes"]*60))
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
        blocked = volatility_guard.entry_block(signal, contract["id"])
        if blocked:
            bot_audit.emit(f"decision:{signal['id']}", "Entry blocked", blocked, signal["id"])
            continue
        enabled = {r["strategy"] for r in history.values() if bot_controls.enabled(signal["symbol"], r["strategy"])}
        blocked = overnight_policy.entry_block(signal, entry_window_history(history.values()), enabled, positions, orders, jobs, contract["id"])
        if blocked:
            bot_audit.emit(f"decision:{signal['id']}", "Entry blocked", blocked, signal["id"])
            continue
        if any(p["contractId"] == contract["id"] for p in positions) or any(o["contractId"] == contract["id"] for o in orders):
            continue
        try:
            selected_quantity = manager_selected[signal["id"]].quantity if manager_selected is not None else entry_quantity(settings["quantities"][micro], positions, jobs)
            payload = build_order({**signal,"entry":confirmation["price"]}, contract, overnight_policy.quantity(selected_quantity))
            check_order_safeguards(payload,gate,positions,orders,jobs)
        except ValueError as error:
            status(f"Signal skipped: {error}")
            continue
        job = dict(alert_id=signal["id"], symbol=micro, contract_id=contract["id"], quantity=payload["size"],
                   strategy=signal["strategy"],strategy_id=signal.get("strategy_id"),entry_mode=signal.get("entry_mode","CONFIRMED"),
                   signal_minutes=signal.get("signal_minutes",15),unique_setup_id=signal.get("unique_setup_id"),
                   config_snapshot=signal.get("config_snapshot"),account_profile=PROFILE,
                   entry_policy=signal.get("entry_policy"),config_fingerprint=signal.get("config_fingerprint"),
                   crossover_key=signal.get("crossover_key"),reference_symbol=signal.get("reference_symbol") or signal["symbol"],
                   consumption_key=signal.get("consumption_key"),box=signal.get("box"),
                   confirmation_method=signal.get("confirmation_method"),
                   source_contract=signal.get("source_contract"),session_id=signal.get("session_id"),
                   candle_time=signal.get("candle_time"),direction=signal.get("direction", signal["signal"]),
                   initial_risk_usd=abs(payload["stopLossBracket"]["ticks"])*MICROS[signal["symbol"]][2]*MICROS[signal["symbol"]][3]*payload["size"],
                   signal_entry=signal["entry"], entry_confirmation=confirmation["reason"], confirmed_entry=confirmation["price"],
                   entry_confirmation_mode=confirmation.get("entry_confirmation_mode"),
                   requested_quantity=settings["quantities"][micro], stop_ticks=abs(payload["stopLossBracket"]["ticks"]),
                   sizing_reason=f"Overnight: configured maximum {overnight_policy.quantity(settings['quantities'][micro])}; manager/risk selected {payload['size']}" if overnight_policy.overnight() else ("Additional symbol: capped at 1 contract" if positions else "First position: selected quantity"),
                   side=payload["side"], state="Intent", sent_at=time.time(), tag=payload["customTag"],
                   automation_session=session_settings(settings).get("id"))
        if not claim(job):
            continue
        try:
            fresh_account = verify_account(token)
            fresh_settings = snapshot()[0]
            fresh_gate = practice_safety.check(fresh_account["balance"], fresh_settings.get("start_balance"), account_id=TARGET["gate_id"])
            if fresh_gate["locked"]:
                pause()
                job.update(state="Rejected", error_message="Not submitted: account loss lock changed during preflight")
                save_job(job)
                return
            if not symbol_enabled(signal["symbol"], snapshot()[0]) or not bot_controls.enabled(signal["symbol"], signal["strategy"]):
                job.update(state="Rejected", error_message="Not submitted: symbol disabled")
                save_job(job)
                return
            fresh_positions, fresh_orders = account_state(token)
            fresh_jobs = snapshot()[2]
            waiting = entry_wait(fresh_positions, fresh_orders, fresh_jobs, own_alert=job["alert_id"], symbol=micro, cooldown_seconds=overnight_policy.cooldown_seconds(bot_controls.read()["cooldown_minutes"]*60))
            if waiting:
                job.update(state="Rejected", error_message=f"Not submitted: {waiting}")
                save_job(job)
                return
            fresh_size = overnight_policy.quantity(entry_quantity(settings["quantities"][micro], fresh_positions, fresh_jobs, own_alert=job["alert_id"]))
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
            if not execution_schedule()["allow_entry"]:
                job.update(state="Rejected",error_message="Not submitted: scheduled entry cutoff")
                save_job(job)
                return
            # Network lookups may have consumed the signal's short entry window.
            latest = read_status().get((signal["symbol"], signal["strategy"]), {})
            now = datetime.now(timezone.utc)
            current_signal = next((r for r in alert_history(10000) if r["id"] == signal["id"]), {})
            if any(current_signal.get(key) != signal.get(key) for key in ("symbol", "strategy", "signal", "unique_setup_id", "config_fingerprint", "crossover_key")):
                job.update(state="Rejected", error_message="Not submitted: claimed signal identity changed during preflight")
                save_job(job)
                return
            if not quote_fresh(latest, now) or not entry_confirmation.window_open(current_signal,now) or current_signal.get("status") != "Active" or not market_session()["is_open"]:
                job.update(state="Rejected", error_message="Not submitted: signal or quote freshness changed during preflight")
                save_job(job)
                return
            fresh_history = alert_history(10000)
            if any(r.get("status") == "Active" and r.get("symbol") == signal["symbol"]
                   and r.get("signal") != current_signal.get("signal")
                   and bot_controls.enabled(r["symbol"], r["strategy"]) for r in entry_window_history(fresh_history, now)):
                job.update(state="Rejected", error_message="Not submitted: conflicting strategy appeared during preflight")
                save_job(job)
                return
            enabled = {r["strategy"] for r in fresh_history if bot_controls.enabled(signal["symbol"], r["strategy"])}
            blocked = overnight_policy.entry_block(current_signal, entry_window_history(fresh_history), enabled, fresh_positions, fresh_orders, fresh_jobs, contract["id"], own_alert=job["alert_id"])
            if blocked or payload["size"] > overnight_policy.quantity(payload["size"]):
                job.update(state="Rejected", error_message=f"Not submitted: {blocked or 'overnight size cap changed during preflight'}")
                save_job(job)
                return
            blocked = volatility_guard.entry_block(current_signal, contract["id"])
            if blocked:
                job.update(state="Rejected", error_message=f"Not submitted: {blocked}")
                save_job(job)
                bot_audit.emit(f"decision:{signal['id']}", "Entry blocked", blocked, signal["id"])
                return
            confirmation = entry_confirmation.check(current_signal)
            if job_session(job):
                from goxtrade.execution.practice_automation import selection
                fresh_settings=snapshot()[0]
                if session_settings(fresh_settings).get("id") != job_session(job):
                    job.update(state="Rejected",error_message="Not submitted: Practice automation session changed")
                    save_job(job)
                    return
                selected=selection(fresh_settings,fresh_history,fresh_account,fresh_gate,fresh_positions,fresh_orders,
                                   snapshot()[2],own_alert=job["alert_id"])
                if signal["id"] not in selected or selected[signal["id"]].quantity != payload["size"]:
                    job.update(state="Rejected",error_message="Not submitted: manager selection/risk changed")
                    save_job(job)
                    return
            if execution_block(current_signal, PROFILE):
                job.update(state="Rejected", error_message="Not submitted: strategy execution eligibility changed")
                save_job(job)
                return
            if confirmation["state"] != "Confirmed" or not entry_confirmation.window_open(current_signal):
                job.update(state="Rejected", error_message=f"Not submitted: {confirmation['reason']}")
                save_job(job)
                return
            payload = build_order({**current_signal,"entry":confirmation["price"]}, contract, payload["size"])
            try:
                check_order_safeguards(payload,fresh_gate,fresh_positions,fresh_orders,fresh_jobs,job['alert_id'])
            except ValueError as error:
                job.update(state='Rejected',error_message=f'Not submitted: {error}')
                save_job(job)
                return
            if job_session(job):
                from goxtrade.execution.practice_automation import validate_payload
                try:
                    job["planned_risk_usd"]=validate_payload(fresh_settings,selected[signal["id"]],payload,micro,fresh_account["balance"],fresh_gate)
                except ValueError as error:
                    job.update(state="Rejected",error_message=f"Not submitted: {error}")
                    save_job(job)
                    return
            if (not snapshot()[0].get("enabled") or not execution_schedule()["allow_entry"]
                    or not quote_fresh(read_status().get((signal["symbol"], signal["strategy"]), {}), datetime.now(timezone.utc))
                    or not entry_confirmation.window_open(current_signal)):
                job.update(state="Rejected", error_message="Not submitted: pause, schedule or freshness changed at send boundary")
                save_job(job)
                return
            job.update(entry_confirmation=confirmation["reason"],confirmed_entry=confirmation["price"],
                       entry_confirmation_mode=confirmation.get("entry_confirmation_mode"),
                       stop_ticks=abs(payload["stopLossBracket"]["ticks"]))
            job["initial_risk_usd"] = abs(payload["stopLossBracket"]["ticks"])*MICROS[signal["symbol"]][2]*MICROS[signal["symbol"]][3]*payload["size"]
            bot_audit.emit(f"confirmation:{signal['id']}", "Entry confirmed", confirmation["reason"], signal["id"])
            assert_current()
            # Persist before HTTP: a crash or timeout after this point is never retried.
            if PROFILE == "practice":
                job["submission_status"] = "SENDING"
                save_job(job)
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
        and (error.response.status_code in (401, 408, 429) or error.response.status_code >= 500)) or (
        isinstance(error,sqlite3.OperationalError) and str(error) in ("database is locked","database table is locked"))
    # Never re-enable here: manual pause and uncertain-submission locks win.
    if retryable:
        bot_audit.emit("connection", "Broker reconnecting", "Temporary API failure; retrying connection. Run/Pause selection preserved; no entries until broker checks succeed.", severity="warning", notify=True)
        status("Broker reconnecting; waiting for successful account reconciliation")
    else:
        pause()
        bot_audit.emit("connection", "Broker unavailable", "Non-transient error; entries paused. Manual account review required.", severity="critical", notify=True)
        status("Practice API error: new entries paused; inspect account before resuming")
    return retryable


def run_practice(wakeup=None):
    global SCHEDULING_MODE
    SCHEDULING_MODE = "event-driven-coalesced-v1" if wakeup is not None else "watchdog"
    token, authenticated = None, 0
    failures = 0
    while True:
        observed = wakeup.version() if wakeup is not None else None
        started = time.monotonic()
        settings, jobs = {}, []
        try:
            settings, _, jobs = snapshot()
            if token is None or time.time() - authenticated > 3600:
                token, authenticated = login(), time.time()
            cycle(token)
            failures = 0
        except Exception as error:
            try:
                recover_connection(error)
            except Exception:
                logging.warning("Execution recovery status unavailable; retrying reconciliation without broker submission")
            failures += 1
            token = None
        active = settings.get("enabled") or settings.get("emergency_close") or any(j["state"] not in ("Closed", "Rejected") for j in jobs)
        if failures:
            # Tick storms must never bypass API recovery backoff or manual pauses.
            Event().wait(min(30, 3 * 2 ** min(failures-1, 4)))
        elif wakeup is not None:
            # Preserve headroom below the provider's shared REST budget. Every cycle
            # still re-reads account/positions/orders and repeats the existing gates.
            wakeup.wait(observed, 3 if active else 15, not_before=started+(2 if active else 15))
        else:
            Event().wait(3 if active else 15)
