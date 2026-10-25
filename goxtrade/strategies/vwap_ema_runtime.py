"""Persistence adapter for the pure VWAP/EMA strategy."""
import pandas as pd

from goxtrade.bot import strategy_events
from goxtrade.bot.signal_lifecycle import track_signal
from goxtrade.data.strategy_history import latest_trade, load_strategy_minutes
from goxtrade.execution.contracts import contract_for_symbol
from goxtrade.market.market_session import session_signal
from goxtrade.strategies.strategy_settings import read_vwap_ema_config
from goxtrade.strategies.vwap_ema_cross import evaluate_vwap_ema_cross


def evaluate_status(symbol, strategy, session, allow_new=True):
    configuration_error = None
    try:
        config = read_vwap_ema_config()
    except (ValueError, KeyError, TypeError) as error:
        from goxtrade.strategies.vwap_ema_config import VwapEmaConfig
        config = VwapEmaConfig(monitor_enabled=False)
        configuration_error = f"Invalid strategy settings: {error}. New entries disabled; existing signal exits remain monitored."
        allow_new = False
    contract = contract_for_symbol(symbol)
    now = pd.Timestamp(session["time"])
    minutes = load_strategy_minutes(symbol, contract, now)
    tick = latest_trade(symbol, contract)
    fresh = bool(tick) and all(
        pd.notna(stamp := pd.to_datetime(tick[field], utc=True, errors="coerce"))
        and 0 <= (now-stamp).total_seconds() <= config.max_data_age_seconds
        for field in ("event_time", "received_at")
    )
    identity = f"vwap_ema_cross|{symbol}|{contract}|{config.fingerprint}"
    persisted_previous = strategy_events.observation(identity)
    previous = dict(persisted_previous)
    prior_event = strategy_events.latest_event(symbol, contract)
    if prior_event and (not previous.get("last_signal_at") or pd.Timestamp(prior_event["detected_at"]) > pd.Timestamp(previous["last_signal_at"])):
        previous.update(last_signal_at=prior_event["detected_at"], last_event_id=prior_event["unique_setup_id"])
    candidate, candles, updated = evaluate_vwap_ema_cross(
        minutes, tick["price"] if tick else None, now, config, previous,
        sequence=tick["id"] if tick else None, quote_time=tick["event_time"] if fresh else None,
        symbol=symbol,
    )
    candidate.update(symbol=symbol, source_contract=contract)
    if configuration_error:
        candidate["reason"] = candidate["trigger_detail"] = configuration_error
    persisted = strategy_events.persist(identity, persisted_previous, updated, candidate)
    if persisted is None:
        allow_new = False
        candidate.update(signal="WAIT", raw_signal="WAIT", direction=None, unique_setup_id=None, crossover_key=None,
                         entry=None, stop=None, target=None,
                         reason="Observation advanced concurrently; waiting for the next trade snapshot.")
    else:
        candidate = persisted
    # Anticipation is explicitly classified; the lifecycle's direction field remains LONG/SHORT.
    if candidate.get("raw_signal", "").startswith("ANTICIPATED_"):
        candidate["signal"] = candidate["direction"]
        candidate["execution_direction_mapping"] = "Explicit Practice-only mapping from " + candidate["raw_signal"]
    management_times = pd.to_datetime(minutes["time"], utc=True, errors="coerce")
    management_source = minutes.loc[management_times+pd.Timedelta(minutes=1) <= now].copy()
    management_source["time"] = management_times.loc[management_source.index]
    if "complete" in management_source:
        management_source = management_source.loc[management_source["complete"].eq(True)]
    management = [{**row, "time": row["time"].isoformat(),
                   "closed_at": (row["time"]+pd.Timedelta(minutes=1)).isoformat()}
                  for row in management_source.to_dict("records")]
    signal = track_signal(symbol, strategy, candidate, candidate.get("unique_setup_id"),
                          allow_new and config.monitor_enabled and session["is_open"] and fresh,
                          management)
    signal = session_signal(signal, session)
    from goxtrade.research.forward_paper import forward_once
    paper = forward_once(symbol, candidate, config, now)
    if config.notify_wait and candidate.get("signal") == "WAIT":
        from goxtrade.bot.bot_audit import emit
        emit(f"vwap-wait:{symbol}", "Strategy waiting", candidate["reason"], notify=True)
    ema, vwap = candidate.get("ema"), candidate.get("vwap")
    focus = f"{ema:,.2f} / {vwap:,.2f}" if ema is not None and vwap is not None else "--"
    return dict(signal=signal, timeframe=f"{config.signal_minutes} min", focus_label=f"EMA{config.ema_length} / VWAP",
                focus_value=focus, entry_mode=config.entry_mode, monitor_enabled=config.monitor_enabled,
                candles=candles, indicator_snapshot=candidate, forward_paper=paper)
