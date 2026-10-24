"""VWAP/EMA crossover calculations only. No database, network, or broker calls."""
import hashlib
import math

import pandas as pd

from goxtrade.market.instruments import instrument
from goxtrade.strategies.vwap_ema_config import VwapEmaConfig
from goxtrade.strategies.vwap_ema_indicators import indicator_frame, utc_time
from goxtrade.strategies.vwap_ema_risk import risk_levels


STRATEGY_ID = "vwap_ema_cross"
STRATEGY_NAME = "VWAP EMA Cross"


def session_allowed(now, config):
    if not config.session_filter_enabled:
        return True
    local = utc_time(now).tz_convert("America/Chicago")
    minute = local.hour * 60 + local.minute
    if "First hour" in config.sessions and 510 <= minute < 570:
        return True
    label = "Regular" if 510 <= minute < 900 else "Extended" if 900 <= minute < 960 else "Overnight"
    if label in config.sessions:
        return True
    if "Custom" in config.sessions:
        for window in config.custom_windows:
            start, end = (int(part[:2])*60 + int(part[3:]) for part in window.split("-"))
            if (start <= minute < end) if start < end else (minute >= start or minute < end):
                return True
    return False


def optional_filters(frame, direction, price, now, config, tick):
    last, prior = frame.iloc[-1], frame.iloc[-2]
    sign = 1 if direction == "LONG" else -1
    atr = float(last["atr"])
    baseline = frame.iloc[:-1].tail(config.volume_lookback)["volume"]
    threshold = max(config.separation_ticks*tick, config.separation_atr*atr if math.isfinite(atr) else 0)
    distance = max(config.max_distance_ticks*tick, config.max_distance_atr*atr if math.isfinite(atr) else 0)
    checks = (
        ("separation", config.separation_enabled, abs(last["gap"]) >= threshold),
        ("ema_slope", config.ema_slope_enabled, (last["ema"]-prior["ema"])*sign > 0),
        ("vwap_slope", config.vwap_slope_enabled, (last["vwap"]-prior["vwap"])*sign > 0),
        ("volume", config.volume_enabled, len(baseline) == config.volume_lookback and last["volume"] >= baseline.mean()*config.volume_multiplier),
        ("volatility", config.volatility_enabled, math.isfinite(atr) and config.atr_min_ticks*tick <= atr <= config.atr_max_ticks*tick),
        ("session", config.session_filter_enabled, session_allowed(now, config)),
        ("distance", config.distance_enabled, abs(price-last["close"]) <= distance),
    )
    return {name: ("passed" if bool(passed) else "failed") if enabled else "disabled"
            for name, enabled, passed in checks}


def evaluate_vwap_ema_cross(minutes, price, now, config=None, previous=None, sequence=None,
                            quote_time=None, historical=False, symbol="NQ=F"):
    """Return (candidate, indicator frame, observation). Intrabar state is caller-owned."""
    config = VwapEmaConfig.from_dict(config)
    now = utc_time(now)
    previous = dict(previous or {})
    state = dict(previous)
    base = dict(signal="WAIT", raw_signal="WAIT", reason="Waiting for initialized indicators.",
                entry=None, stop=None, target=None, range_low=None, range_high=None,
                last_close=price, strategy_id=STRATEGY_ID, strategy=STRATEGY_NAME,
                signal_minutes=config.signal_minutes, entry_mode=config.entry_mode,
                entry_policy="indicator-event-v1", entry_window_seconds=config.entry_window_seconds,
                config_snapshot=config.to_dict(), config_fingerprint=config.fingerprint,
                account_eligibility={"leader": False, "practice": config.practice_enabled},
                detected_at=now.isoformat(), detection_sequence=sequence, filter_results={})

    def waiting(reason, frame=None):
        return {**base, "reason": reason, "trigger_detail": reason}, pd.DataFrame() if frame is None else frame, state

    if not config.monitor_enabled or symbol not in config.enabled_symbols:
        return waiting("Strategy monitoring is disabled for this symbol.")
    if price is None or not math.isfinite(float(price)) or price <= 0:
        return waiting("A valid current trade price is required.")
    if not historical:
        if quote_time is None or not 0 <= (now-utc_time(quote_time)).total_seconds() <= config.max_data_age_seconds:
            return waiting("Fresh trade data is required; no signal on stale data.")
    try:
        frame = indicator_frame(minutes, now, config, sequence)
    except (ValueError, KeyError, TypeError) as error:
        return waiting(f"Data integrity: {error}")
    if len(frame) < 2:
        return waiting("Need complete, consecutive signal candles and full session history.", frame)
    last, prior = frame.iloc[-1], frame.iloc[-2]
    expected = now.floor(f"{config.signal_minutes}min")
    if config.entry_mode == "CONFIRMED":
        expected -= pd.Timedelta(minutes=config.signal_minutes)
    base.update(ema=float(last["ema"]) if pd.notna(last["ema"]) else None,
                vwap=float(last["vwap"]) if pd.notna(last["vwap"]) else None,
                indicator_distance=float(last["gap"]) if pd.notna(last["gap"]) else None,
                session_id=last["session_id"], candle_time=last["time"].isoformat(),
                setup_time=last["time"].isoformat(), provisional=bool(last["provisional"]),
                signal_price=float(last["close"]), crossover_price=float(last["close"]))
    if last["time"] != expected or bool(last["provisional"]) != (config.entry_mode != "CONFIRMED"):
        return waiting("Current signal bucket is incomplete or unavailable for this entry mode.", frame)
    if not last["coverage"] or not prior["coverage"]:
        return waiting("Full trade-minute coverage from the configured session anchor is required.", frame)
    if last["session_id"] != prior["session_id"]:
        return waiting("Session reset: wait for two candles within the same VWAP session.", frame)
    if last["warmup"] < config.warmup_bars or not all(pd.notna(value) for value in (prior["ema"], last["ema"], prior["vwap"], last["vwap"])):
        return waiting(f"EMA warmup: need {config.warmup_bars} valid signal candles.", frame)
    if last["volume"] <= 0:
        return waiting("The current signal candle has no traded volume.", frame)
    differences = frame["gap"]
    crossed = ((differences.shift() <= 0) & (differences > 0)) | ((differences.shift() >= 0) & (differences < 0))
    crossed &= frame["session_id"].eq(frame["session_id"].shift()) & frame["coverage"] & frame["coverage"].shift(fill_value=False)
    history = frame.loc[crossed & ~frame["provisional"]]
    base["latest_crossover_direction"] = ("LONG" if history.iloc[-1]["gap"] > 0 else "SHORT") if not history.empty else None
    base["last_signal_timestamp"] = history.iloc[-1]["closed_at"].isoformat() if not history.empty else None
    direction = None
    if config.entry_mode == "CONFIRMED":
        if prior["gap"] <= 0 < last["gap"]:
            direction = "LONG"
        elif prior["gap"] >= 0 > last["gap"]:
            direction = "SHORT"
    else:
        if sequence is None:
            return waiting("Ordered trade observations are required for intrabar modes.", frame)
        if previous.get("config_fingerprint") != config.fingerprint or previous.get("session_id") != last["session_id"]:
            previous = {}
        last_sequence = previous.get("sequence", -1)
        if int(sequence) < last_sequence:
            return waiting("Out-of-order observation rejected.", frame)
        if int(sequence) == last_sequence:
            return waiting("No new trade observation.", frame)
        stamp = previous.get("time")
        continuous = bool(stamp) and 0 <= (now-utc_time(stamp)).total_seconds() <= config.max_data_age_seconds
        old_gap = previous.get("gap") if continuous else None
        state.update(config_fingerprint=config.fingerprint, session_id=last["session_id"],
                     sequence=int(sequence), time=now.isoformat(), gap=float(last["gap"]), convergence_count=0)
        if old_gap is None:
            return waiting("Observation baseline established; waiting for a newly observed event.", frame)
        if config.entry_mode == "REALTIME":
            direction = "LONG" if old_gap <= 0 < last["gap"] else "SHORT" if old_gap >= 0 > last["gap"] else None
        else:
            approaching = abs(last["gap"]) < abs(old_gap) and old_gap*last["gap"] > 0
            proposed = "LONG" if last["gap"] < 0 else "SHORT"
            sign = 1 if proposed == "LONG" else -1
            supporting = ((last["ema"]-prior["ema"])*sign > config.anticipation_min_slope_ticks*instrument(symbol).tick_size
                          and (last["close"]-prior["close"])*sign > 0)
            if approaching and supporting and abs(last["gap"]) <= config.anticipation_distance_ticks*instrument(symbol).tick_size:
                count = previous.get("convergence_count", 0) + 1 if previous.get("anticipated_direction") == proposed else 1
                state.update(convergence_count=count, anticipated_direction=proposed)
                if count >= config.anticipation_observations:
                    direction = proposed
            else:
                state["anticipated_direction"] = None
    if direction is None:
        return waiting("No new crossover." if config.entry_mode != "ANTICIPATORY" else "No qualifying pre-cross convergence sequence.", frame)
    signal_at = last["closed_at"] if config.entry_mode == "CONFIRMED" else now
    if not 0 <= (now-signal_at).total_seconds() < config.entry_window_seconds:
        return waiting("Crossover entry window has expired.", frame)
    identity = "|".join((STRATEGY_ID, symbol, str(minutes.attrs.get("contract_id", "")),
                         last["session_id"], str(config.signal_minutes), config.entry_mode,
                         last["time"].isoformat(), direction))
    event_id = hashlib.sha256(identity.encode()).hexdigest()
    last_signal = previous.get("last_signal_at")
    if last_signal and previous.get("last_event_id") != event_id and (now-utc_time(last_signal)).total_seconds() < config.cooldown_minutes*60:
        return waiting("Strategy crossover cooldown is active.", frame)
    filters = optional_filters(frame, direction, price, now, config, instrument(symbol).tick_size)
    base["filter_results"] = filters
    failed = [name for name, result in filters.items() if result == "failed"]
    if failed:
        return waiting("Optional filters blocked entry: " + ", ".join(failed), frame)
    closed_minutes = minutes.loc[pd.to_datetime(minutes["time"], utc=True)+pd.Timedelta(minutes=1) <= now].copy()
    try:
        levels = risk_levels(direction, price, frame, closed_minutes, config, instrument(symbol).tick_size)
    except ValueError as error:
        return waiting(str(error), frame)
    raw_signal = "ANTICIPATED_" + direction if config.entry_mode == "ANTICIPATORY" else direction
    detail = (f"{config.entry_mode} / {config.signal_minutes}m EMA{config.ema_length} {last['ema']:.5f}; "
              f"{config.vwap_source.upper()} session VWAP {last['vwap']:.5f}; gap {last['gap']:.5f}. "
              f"Candle {last['time'].isoformat()}; detected {now.isoformat()}; sequence {sequence}.")
    state.update(last_event_id=event_id,
                 last_signal_at=last_signal if previous.get("last_event_id") == event_id else now.isoformat())
    return {**base, **levels, "signal": raw_signal, "raw_signal": raw_signal, "direction": direction,
            "setup_id": event_id, "unique_setup_id": event_id, "signal_timestamp": signal_at.isoformat(),
            "confirmed_at": signal_at.isoformat() if config.entry_mode == "CONFIRMED" else None, "classification": raw_signal,
            "reason": detail, "trigger_detail": detail}, frame, state
