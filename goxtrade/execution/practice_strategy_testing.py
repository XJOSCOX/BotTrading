"""Explicit Practice sessions bridge the existing pure manager to the executor."""
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import uuid

from goxtrade.config import execution_identity as identity
from goxtrade.execution.execution_policy import ExecutionPolicy
from goxtrade.execution.portfolio_risk import PortfolioState
from goxtrade.execution.trade_candidate import adapt_alert, stamp
from goxtrade.execution.strategy_manager import evaluate
from goxtrade.strategies.strategy_catalog import strategy_spec


def start(strategies, confirmed_account, confirmed):
    from goxtrade.execution import practice_executor as executor, manager_service
    from goxtrade.bot import bot_controls
    from goxtrade.strategies.strategy_settings import read_vwap_ema_config, save_vwap_ema_config
    from goxtrade.market.calendar_guard import entry_block
    if identity.PROFILE != "practice" or executor.PROFILE != "practice":
        raise ValueError("Practice process only; Leader cannot start strategy testing")
    identity.assert_current()
    if confirmed is not True or confirmed_account != executor.ACCOUNT_NAME:
        raise ValueError("Confirm the exact isolated Practice account and Auto OCO")
    specs = [strategy_spec(value) for value in strategies]
    if not specs or len({s.id for s in specs}) != len(specs) or any("practice" not in s.execution_profiles for s in specs):
        raise ValueError("Select unique registered Practice strategies")
    settings, _, _ = executor.snapshot()
    if settings.get("enabled"):
        raise ValueError("Pause new entries before changing the test session")
    with closing(executor.db()) as conn:
        identity.assert_other_idle(conn)
    blocked = entry_block(datetime.now(timezone.utc))
    if blocked:
        raise ValueError(blocked)
    base_policy = manager_service.policy()
    policy = replace(base_policy, symbols=("MNQ",),
        monitoring=tuple(s.id for s in specs), participating=tuple(s.id for s in specs), priority=tuple(s.id for s in specs),
        requested_quantity=1, max_contracts=1, max_positions=1, max_group_positions=1,
        max_trade_risk=min(base_policy.max_trade_risk, settings["max_trade_loss"]),
        commission_per_side=base_policy.commission_per_side if base_policy.commission_per_side is not None else 1.)
    policy.validate()
    if any(s.id == "vwap_ema_cross" for s in specs):
        config = read_vwap_ema_config()
        save_vwap_ema_config(replace(config, practice_enabled=True, monitor_enabled=True,
            entry_mode="CONFIRMED", signal_minutes=3, ema_length=9, ema_source="close", vwap_source="ohlc4",
            enabled_symbols=("MNQ=F",)))
    if any(s.id == "previous_day_box" for s in specs):
        from goxtrade.strategies.strategy_settings import read_previous_day_box_config, save_previous_day_box_config
        save_previous_day_box_config(replace(read_previous_day_box_config(), practice_enabled=True))
    controls = bot_controls.read("practice")
    bot_controls.save(["MNQ"], [s.name for s in specs], controls["cooldown_minutes"], profile="practice")
    quantities = {**settings["quantities"], "MNQ":1}
    session = dict(id=uuid.uuid4().hex, account_id=executor.ACCOUNT_ID, strategies=[s.id for s in specs],
                   instrument="MNQ", started_at=datetime.now(timezone.utc).isoformat(), policy=policy.to_dict())
    executor.arm(settings["max_trade_loss"], settings["max_run_loss"], True,
                 quantities=quantities, enable_mym=settings.get("enable_mym",False), strategy_testing=session)
    return session


def selection(settings, history, account, gate, positions, orders, jobs, *, own_alert=None, now=None):
    """Manager selects; existing atomic job claim and transport remain authoritative."""
    from goxtrade.execution import practice_executor as executor
    from goxtrade.execution.contracts import contract_for_symbol
    from goxtrade.execution.signal_reservations import initialize, persist_decisions
    from goxtrade.execution.executed_results import results
    from goxtrade.execution.practice_history import snapshot as fills_snapshot
    from goxtrade.data.strategy_history import latest_trade
    from goxtrade.strategies import entry_confirmation
    from goxtrade.strategies.strategy_catalog import order_block
    from goxtrade.bot import bot_audit
    from goxtrade.research.portfolio_forward_paper import trading_day
    session = settings.get("strategy_testing") or {}
    if identity.PROFILE != "practice" or executor.PROFILE != "practice" or session.get("account_id") != executor.ACCOUNT_ID:
        raise ValueError("Exact Practice strategy session is required")
    live_clock = now is None
    now = now or datetime.now(timezone.utc)
    policy = ExecutionPolicy.from_dict(session["policy"])
    contract = contract_for_symbol("MNQ=F")
    active = [j for j in jobs if j["state"] not in ("Closed","Rejected") and j["alert_id"] != own_alert]
    matched = results(jobs, fills_snapshot()[1])
    day = trading_day(now)
    today = [j for j in jobs if j.get("strategy_testing_session") and
             trading_day(datetime.fromtimestamp(j["sent_at"],timezone.utc)) == day]
    closed = sorted((j for j in today if j["state"] == "Closed"), key=lambda j:j.get("closed_confirmed_at",""), reverse=True)
    losses = 0
    for job in closed:
        if job["alert_id"] not in matched or matched[job["alert_id"]]["net"] >= 0: break
        losses += 1
    unresolved_results = any(j["alert_id"] not in matched for j in closed)
    from goxtrade.market.trading_schedule import execution_schedule
    schedule=execution_schedule(now)
    state = PortfolioState(str(executor.ACCOUNT_ID), "practice", now.isoformat(),
        realized=min(account["balance"]-settings["start_balance"], -max(0,gate.get("loss",0))),
        armed=settings.get("enabled") is True, paused=settings.get("enabled") is not True,
        emergency=settings.get("emergency_close") is True, loss_locked=gate.get("locked") is True,
        reconciled=True, unresolved=bool(positions or orders or active or unresolved_results),
        session_allowed=schedule["allow_entry"] and not schedule["flatten"],
        daily_trades=len([j for j in today if j["state"] != "Rejected" and j["alert_id"] != own_alert]),
        consecutive_losses=losses,
        last_closed_at=max((j["closed_confirmed_at"] for j in jobs if j.get("state")=="Closed" and j.get("closed_confirmed_at")),default=None),
        contracts=(("MNQ",contract),), practice_session_authorized=True)
    consumed={j["alert_id"] for j in jobs if j["alert_id"] != own_alert}
    candidates, source = [], {}
    for alert in history:
        if (alert.get("status") != "Active" or alert["id"] <= settings["after_id"] or alert["id"] in consumed
                or alert.get("symbol") != "NQ=F"):
            continue
        try:
            spec = strategy_spec(alert.get("strategy_id") or alert["strategy"])
            if spec.id not in session["strategies"]: continue
            confirmation = entry_confirmation.check(alert,now)
            quote = latest_trade("MNQ=F",contract)
            confirmed = alert.get("confirmed_at") or (stamp(alert["setup_time"])+timedelta(minutes=spec.signal_minutes)).isoformat()
            expiry = stamp(confirmed)+timedelta(seconds=alert.get("entry_window_seconds",600 if spec.runtime_adapter is None else spec.expiration_seconds))
            envelope={**alert,"unique_setup_id":alert.get("unique_setup_id") or f"alert:{alert['id']}",
                      "exit_mode":alert.get("exit_mode","structure-v1")}
            candidate=adapt_alert(envelope,account_id=str(executor.ACCOUNT_ID),profile="practice",symbol="MNQ",contract_id=contract,
                price=confirmation.get("price"),quote_at=quote["event_time"] if quote else None,
                confirmed_at=confirmed,expires_at=expiry.isoformat(),confirmed=confirmation["state"]=="Confirmed",
                history_complete=confirmation["state"]=="Confirmed",execution_eligible=not order_block(alert,"practice",now),
                session=alert.get("session_id") or day)
            candidates.append(candidate); source[candidate.candidate_id]=alert["id"]
        except (ValueError,TypeError,KeyError) as error:
            bot_audit.emit(f"decision:{alert['id']}","Entry blocked","Manager envelope unavailable: "+str(error),alert["id"])
    if live_clock:
        now=datetime.now(timezone.utc)
        state=replace(state,observed_at=now.isoformat())
    decisions=evaluate(candidates,state,policy,now.isoformat(),scope="broker")
    with closing(executor.db()) as conn:
        initialize(conn)
        persist_decisions(conn,candidates,state,policy,now.isoformat(),decisions,"practice_strategy_test")
        conn.commit()
    selected={source[d.candidate_id]:d for d in decisions if d.selected}
    for decision in decisions:
        if not decision.selected:
            alert_id=source[decision.candidate_id]
            bot_audit.emit(f"decision:{alert_id}","Entry blocked","Manager: "+"; ".join(decision.reasons),alert_id)
    return selected
