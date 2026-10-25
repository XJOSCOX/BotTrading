"""Local manager persistence and shadow read models. Never imports a broker client."""
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import pandas as pd

from goxtrade.data.live_store import connect
from goxtrade.execution.execution_policy import ExecutionPolicy
from goxtrade.execution.portfolio_risk import PortfolioState
from goxtrade.execution.signal_reservations import initialize, persist_decisions
from goxtrade.execution.strategy_manager import evaluate
from goxtrade.execution.trade_candidate import adapt_alert, digest, finite, frozen_json, stamp


def read_policy(conn):
    row = conn.execute("SELECT record FROM manager_settings WHERE id=1").fetchone()
    return ExecutionPolicy.from_dict(json.loads(row[0])) if row else ExecutionPolicy()


def policy():
    with closing(connect()) as conn:
        initialize(conn)
        return read_policy(conn)


def save_policy(values):
    settings = ExecutionPolicy.from_dict(values)
    with closing(connect()) as conn:
        initialize(conn)
        conn.execute("INSERT INTO manager_settings VALUES (1,?) ON CONFLICT(id) DO UPDATE SET record=excluded.record", (frozen_json(settings.to_dict()),))
        conn.commit()
    return settings


def shadow(profile, *, persist=False, now=None):
    """Snapshot existing alerts and broker health locally, without polling or submission."""
    from goxtrade.api.state import snapshot
    from goxtrade.bot.bot_health import snapshot as health_snapshot
    from goxtrade.bot.bot_controls import read
    from goxtrade.config.execution_identity import TARGETS
    from goxtrade.data.strategy_history import latest_trade
    from goxtrade.execution.contracts import contract_for_symbol
    from goxtrade.market.trading_schedule import execution_schedule
    from goxtrade.strategies.entry_confirmation import check
    from goxtrade.strategies.strategy_catalog import strategy_spec, order_block
    from goxtrade.research.portfolio_forward_paper import trading_day
    if profile not in ("practice", "leader"):
        raise ValueError("Unknown account view")
    now = stamp(now or datetime.now(timezone.utc))
    settings = policy()
    data = snapshot()
    account = data["profiles"][profile]
    health = health_snapshot(account.get("broker"), account_id=TARGETS[profile]["gate_id"])
    health_time = health.get("updated_at")
    fresh = False
    try:
        fresh = not health.get("error", True) and 0 <= (now-stamp(health_time)).total_seconds() <= 10
    except (ValueError, TypeError):
        pass
    schedule = execution_schedule(now)
    controls = read(profile)
    enabled = account.get("settings", {}).get("enabled") is True
    unresolved = bool(health.get("positions") or health.get("orders")) or any(job.get("state") not in ("Closed", "Rejected") for job in account["jobs"])
    gate = account.get("gate", {})
    verified_loss = finite(gate.get("loss")) and gate["loss"] >= 0 and type(gate.get("locked")) is bool
    # Open-account risk must not be guessed from a signal stop or a summary count.
    contracts = {symbol: contract_for_symbol(symbol+"=F") for symbol in settings.symbols}
    facts = PortfolioState(str(TARGETS[profile]["id"]), profile, now.isoformat(), armed=enabled, reconciled=fresh,
        paused=not enabled, emergency=account["settings"].get("emergency_close") is True,
        loss_locked=gate.get("locked") is True, realized=-gate["loss"] if verified_loss else 0., unresolved=unresolved or not verified_loss,
        session_allowed=schedule["allow_entry"], session_reason=schedule["reason"], contracts=tuple(contracts.items()))
    candidates, rejected = [], []
    for alert in data["alerts"]:
        if alert.get("status") != "Active":
            continue
        try:
            spec = strategy_spec(alert.get("strategy_id") or alert["strategy"])
            symbol = {"NQ=F": "MNQ", "ES=F": "MES", "YM=F": "MYM"}.get(alert.get("symbol"))
            contract = contracts.get(symbol)
            if not contract:
                raise ValueError("Actual executable contract not configured for this instrument")
            quote = latest_trade(symbol+"=F", contract)
            confirmation = check(alert, now)
            confirmed = alert.get("confirmed_at") or (pd.Timestamp(alert["setup_time"])+pd.Timedelta(minutes=spec.signal_minutes)).isoformat()
            expiry = stamp(confirmed)+timedelta(seconds=alert.get("entry_window_seconds", 600 if profile == "practice" and spec.runtime_adapter is None else 300 if spec.runtime_adapter is None else spec.expiration_seconds))
            permitted = (profile in spec.execution_profiles and spec.name in controls["strategies"]
                         and symbol in controls["symbols"] and not order_block(alert, profile, now))
            candidate = adapt_alert(alert, account_id=facts.account_id, profile=profile, symbol=symbol, contract_id=contract,
                price=confirmation.get("price"), quote_at=quote["event_time"] if quote else None,
                confirmed_at=confirmed, expires_at=expiry.isoformat(), confirmed=confirmation["state"] == "Confirmed",
                history_complete=confirmation["state"] == "Confirmed", execution_eligible=permitted, session=alert.get("session_id") or trading_day(now))
            candidates.append(candidate)
        except (ValueError, TypeError, KeyError):
            rejected.append(dict(alert_id=alert.get("id"), strategy=alert.get("strategy"), reason="Cannot form a complete validated execution envelope; watch only"))
    if not fresh:
        facts = replace(facts, reconciled=False)
    decisions = evaluate(candidates, facts, settings, now.isoformat(), scope="shadow")
    if persist:
        with closing(connect()) as conn:
            initialize(conn)
            persist_decisions(conn, candidates, facts, settings, now.isoformat(), decisions, "shadow")
            conn.commit()
    return dict(profile=profile, scope="SHADOW - NO BROKER AUTHORIZATION", policy=settings.to_dict(),
                candidates=[c.to_dict() for c in candidates], decisions=[d.to_dict() for d in decisions],
                adapter_rejections=rejected, broker_fresh=fresh, broker_observed_at=health_time,
                account_armed=enabled, account_exposure_unresolved=unresolved, account_loss_snapshot_verified=verified_loss, session=schedule,
                risk_note="Existing account exposure blocks shadow selection until owned protective risk can be verified",
                broker_cutover_enabled=False)


def overview(profile):
    result = shadow(profile)
    with closing(connect()) as conn:
        initialize(conn)
        result["journal"] = [json.loads(row[0]) for row in conn.execute("SELECT record FROM manager_decisions ORDER BY decision_at DESC LIMIT 200")]
        result["reservations"] = [json.loads(row[0]) for row in conn.execute("SELECT record FROM manager_reservations WHERE status NOT IN ('closed','rejected')")]
        result["runs"] = [dict(id=row[0], kind=row[1], record=json.loads(row[2])) for row in conn.execute("SELECT id,kind,record FROM manager_simulation ORDER BY rowid DESC LIMIT 20")]
    return result


def save_simulation(result):
    identifier = digest(result)
    with closing(connect()) as conn:
        initialize(conn)
        conn.execute("INSERT OR IGNORE INTO manager_simulation VALUES (?,?,?)", (identifier, result["kind"], frozen_json(result)))
        conn.commit()
    return identifier


def paper_once(now=None):
    """Explicit paper mode only; saved state uses compare-and-swap across workers."""
    from goxtrade.research.portfolio_forward_paper import empty_portfolio, advance_portfolio, manage_completed, portfolio_summary
    from goxtrade.research.portfolio_backtest import candidates_at, session_facts
    from goxtrade.data.strategy_history import load_strategy_minutes
    from goxtrade.execution.contracts import contract_for_symbol
    now = pd.Timestamp(now or datetime.now(timezone.utc)).tz_convert("UTC")
    with closing(connect()) as conn:
        initialize(conn)
        settings = read_policy(conn)
        row = conn.execute("SELECT record FROM manager_simulation WHERE id='portfolio-paper'").fetchone()
        previous = row[0] if row else None
        old = json.loads(previous)["state"] if previous else empty_portfolio()
        if not settings.paper_enabled and not old["positions"] and not old["pending"]:
            return dict(message="Portfolio paper disabled", enabled=False)
        if old.get("last_poll_at") and now < pd.Timestamp(old["last_poll_at"]):
            raise ValueError("Paper observation clock moved backwards")
        contracts = {symbol: contract_for_symbol(symbol+"=F") for symbol in settings.symbols}
        # Preserve old-contract exits after rollover or symbol removal.
        watched = set(contracts.items()) | {(p["exposure"]["symbol"], p["exposure"]["contract_id"]) for p in (*old["positions"], *old["pending"])}
        if previous is None:
            old["cursor"] = conn.execute("SELECT COALESCE(MAX(id),0) FROM live_ticks").fetchone()[0]
        rows = [dict(row) for row in conn.execute("SELECT id,price,event_time,received_at,symbol,contract_id FROM live_ticks WHERE id>? AND event_type='trade' AND price IS NOT NULL ORDER BY id LIMIT 20000", (old["cursor"],))]
    observations = []
    last_time = stamp(old["last_observed_at"]) if old.get("last_observed_at") else None
    cursor = old["cursor"]
    rejections = []
    for row in rows:
        cursor = row["id"]
        symbol = row["symbol"].removesuffix("=F")
        if (symbol, row["contract_id"]) not in watched:
            continue
        try:
            event, received = stamp(row["event_time"]), stamp(row["received_at"])
            if not 0 <= (received-event).total_seconds() <= 10 or event > stamp(now.to_pydatetime()) or (last_time and event < last_time):
                raise ValueError("Late or future trade observation")
            if old.get("last_poll_at") and event < stamp(old["last_poll_at"]):
                raise ValueError("Trade arrived after an already-decided snapshot")
            observations.append(dict(sequence=row["id"], price=row["price"], time=event.isoformat(), symbol=symbol, contract_id=row["contract_id"]))
            last_time = event
        except ValueError:
            rejections.append(dict(time=now.isoformat(), reason="Rejected late/future/unverified trade; no retrospective paper fill"))
    state = old
    # Each tick's own calendar controls pending fills; current wall time cannot authorize stale ticks.
    for observation in observations:
        when = pd.Timestamp(observation["time"])
        schedule = session_facts(when)
        state = advance_portfolio(state, [], [observation], settings, when.isoformat(), contracts=contracts,
                                  session_allowed=schedule["allow_entry"], session_reason=schedule["reason"], flatten=schedule["flatten"])
    histories, prices = {}, {}
    for symbol, contract in contracts.items():
        if not contract:
            continue
        histories[symbol] = load_strategy_minutes(symbol+"=F", contract, now, hours=24*16)
        mark = state["marks"].get(symbol)
        if mark and mark["contract_id"] == contract and 0 <= (now-pd.Timestamp(mark["time"])).total_seconds() <= 10:
            prices[symbol] = mark["price"]
    try:
        candidates, waits = candidates_at(histories, prices, contracts, now, settings, account=state["account"], profile="paper", configurations=shared_strategy_configs(),
                                         quote_times={symbol: state["marks"][symbol]["time"] for symbol in prices}) if settings.paper_enabled else ([], [])
    except ValueError:
        candidates, waits = [], [dict(time=now.isoformat(), reason="Strategy configuration unavailable; new portfolio paper entries blocked, owned exits retained")]
    schedule = session_facts(now)
    state = advance_portfolio(state, candidates, [], settings, now.isoformat(), contracts=contracts,
                              session_allowed=schedule["allow_entry"], session_reason=schedule["reason"], flatten=schedule["flatten"])
    for symbol, contract in watched:
        if contract:
            bars = histories.get(symbol) if contracts.get(symbol) == contract else load_strategy_minutes(symbol+"=F", contract, now)
            if bars is not None:
                manage_completed(state, symbol, bars, now)
    state["data_rejections"].extend(rejections+waits)
    state["cursor"], state["last_poll_at"] = cursor, now.isoformat()
    result = dict(kind="portfolio_forward_paper", state=state, summary=portfolio_summary(state), broker_checks="NOT_PERFORMED")
    with closing(connect()) as conn:
        initialize(conn)
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute("SELECT record FROM manager_simulation WHERE id='portfolio-paper'").fetchone()
        if (current[0] if current else None) != previous:
            conn.rollback()
            return dict(message="Paper state advanced concurrently; no duplicate accounting")
        conn.execute("INSERT INTO manager_simulation VALUES ('portfolio-paper',?,?) ON CONFLICT(id) DO UPDATE SET record=excluded.record", (result["kind"], frozen_json(result)))
        conn.commit()
    return result


def shared_strategy_configs():
    from goxtrade.strategies.strategy_settings import read_vwap_ema_config, read_previous_day_box_config, read_stop_minutes, read_orb_minutes
    from goxtrade.strategies.strategy_catalog import SPECS
    values = {spec.id: dict(management_minutes=read_stop_minutes(), orb_minutes=read_orb_minutes()) for spec in SPECS if spec.runtime_adapter is None}
    values.update(vwap_ema_cross=read_vwap_ema_config().to_dict(), previous_day_box=read_previous_day_box_config().to_dict())
    return values
