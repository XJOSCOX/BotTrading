"""Chronological competing-strategy simulation, not summed independent P&L."""
from dataclasses import replace
import copy
import json

import pandas as pd

from goxtrade.execution.trade_candidate import adapt_alert
from goxtrade.market.instruments import instrument, validate_contract_instrument
from goxtrade.market.trading_schedule import execution_schedule
from goxtrade.research.adapters import legacy_candidate
from goxtrade.research.datasets import validate_dataset, dataset_hash, UnsupportedDataset
from goxtrade.research.portfolio_forward_paper import (advance_portfolio, close_position, empty_portfolio,
                                                      manage_completed, portfolio_summary, trading_day)
from goxtrade.strategies.strategy_catalog import strategy_spec


def session_facts(now):
    """Offline exchange calendar plus account cutoff; never live broker preflight."""
    from goxtrade.strategies.previous_day_box_sessions import session_windows
    from goxtrade.strategies.previous_day_box_config import PreviousDayBoxConfig
    windows = session_windows(now, PreviousDayBoxConfig())
    current = next((w for w in windows if any(a <= now < b for a, b in w["segments"])), None)
    schedule = execution_schedule(now.to_pydatetime(), calendar=False)
    if current is None:
        return dict(allow_entry=False, flatten=True, reason="Historical exchange calendar: closed")
    remaining = current["close"]-now
    return dict(allow_entry=schedule["allow_entry"] and remaining > pd.Timedelta(minutes=15),
                flatten=schedule["flatten"] or remaining <= pd.Timedelta(minutes=5),
                reason=schedule["reason"] if remaining > pd.Timedelta(minutes=15) else "Exchange early-close buffer")


def candidates_at(histories, prices, contracts, now, policy, *, account, profile, configurations=None, quote_times=None):
    """All seven adapters retain their own confirmation and frozen exit rules."""
    from goxtrade.strategies.entry_confirmation import evaluate as confirm_legacy
    from goxtrade.strategies.vwap_ema_config import VwapEmaConfig
    from goxtrade.strategies.vwap_ema_cross import evaluate_vwap_ema_cross
    from goxtrade.strategies.previous_day_box_config import PreviousDayBoxConfig
    from goxtrade.strategies.previous_day_box import evaluate_previous_day_box
    configurations = configurations or {}
    candidates, waits = [], []
    for symbol in sorted(histories):
        if symbol not in policy.symbols or symbol not in prices or symbol not in contracts:
            continue
        known = histories[symbol]
        if known.empty:
            continue
        contract, price = contracts[symbol], prices[symbol]
        reference = {"MNQ": "NQ=F", "MES": "ES=F", "MYM": "YM=F"}.get(symbol, symbol+"=F")
        for strategy in policy.participating:
            spec = strategy_spec(strategy)
            values = configurations.get(spec.id, {})
            try:
                if known.attrs.get("contract_id") != contract or known["time"].duplicated().any() or ("complete" in known and not known["complete"].eq(True).all()):
                    raise ValueError("Unverified contract provenance or incomplete required history")
                if spec.id == "vwap_ema_cross":
                    config = replace(VwapEmaConfig.from_dict(values), monitor_enabled=True, enabled_symbols=(reference,))
                    if config.entry_mode != "CONFIRMED":
                        raise UnsupportedDataset("Portfolio minute replay supports CONFIRMED indicator mode only; intrabar signals require recorded trades")
                    raw, _, _ = evaluate_vwap_ema_cross(known, price, now, config, historical=True, symbol=reference)
                    config_values = config.to_dict()
                elif spec.id == "previous_day_box":
                    config = replace(PreviousDayBoxConfig.from_dict(values), monitor_enabled=True, enabled_symbols=(reference,))
                    raw, _ = evaluate_previous_day_box(known, price, now, config, symbol=reference, contract_id=contract, historical=True)
                    config_values = config.to_dict()
                else:
                    config_values = values
                    raw = legacy_candidate(known, price, now, symbol, spec.name, values)
                if raw.get("direction", raw.get("signal")) not in ("LONG", "SHORT"):
                    waits.append(dict(strategy_id=spec.id, symbol=symbol, time=now.isoformat(), reason=raw.get("reason", "No confirmed setup")))
                    continue
                created = now.isoformat()
                confirmed_at = raw.get("confirmed_at") or (pd.Timestamp(raw["setup_time"])+pd.Timedelta(minutes=spec.signal_minutes)).isoformat()
                expiry = pd.Timestamp(confirmed_at)+pd.Timedelta(seconds=raw.get("entry_window_seconds", 600 if spec.runtime_adapter is None else spec.expiration_seconds))
                valid = True
                if spec.runtime_adapter is None:
                    confirmed = confirm_legacy({**raw, "status": "Active", "symbol": reference}, known, price, now)
                    valid = confirmed["state"] == "Confirmed"
                    if not valid:
                        raw["reason"] = confirmed["reason"]
                candidate = adapt_alert({**raw, "strategy_id": spec.id, "strategy": spec.name, "symbol": reference, "detected_at": created},
                    account_id=account, profile=profile, symbol=symbol, contract_id=contract, price=price, quote_at=(quote_times or {}).get(symbol, created),
                    confirmed_at=confirmed_at, expires_at=expiry.isoformat(), confirmed=valid,
                    history_complete=True, execution_eligible=True, config=config_values,
                    session=trading_day(now.to_pydatetime()))
                candidates.append(candidate)
            except UnsupportedDataset:
                raise
            except (ValueError, TypeError, KeyError, IndexError) as error:
                waits.append(dict(strategy_id=spec.id, symbol=symbol, time=now.isoformat(), reason=f"Adapter unavailable: {type(error).__name__}"))
    return candidates, waits


def run_portfolio_backtest(datasets, policy, configurations=None, candidate_source=None, profit_policy=None):
    """Each dataset is explicit (instrument, actual contract, finalized minute frame)."""
    policy.validate()
    if policy.commission_per_side is None:
        raise ValueError("Portfolio backtest requires explicit costs")
    frames, contracts, hashes = {}, {}, {}
    for symbol, contract, frame in datasets:
        if symbol in frames:
            raise ValueError("One actual contract per instrument/run; split rollovers")
        validate_contract_instrument(symbol, contract)
        source = validate_dataset(frame, contract)
        tick = instrument(symbol).tick_size
        if ((source[["open", "high", "low", "close"]]/tick).sub((source[["open", "high", "low", "close"]]/tick).round()).abs() > 1e-6).any().any():
            raise ValueError("Historical OHLC does not match instrument tick grid")
        frames[symbol], contracts[symbol], hashes[symbol] = source, contract, dataset_hash(source)
    if not frames:
        raise ValueError("Actual historical datasets required; no synthetic fallback")
    state = empty_portfolio("portfolio-backtest", "research")
    observations = {symbol: {row["time"]: row for row in frame.to_dict("records")} for symbol, frame in frames.items()}
    times = sorted(set().union(*(set(rows) for rows in observations.values())))
    previous, sequence = {}, 0
    for now in times:
        schedule = session_facts(now)
        present = {symbol: rows[now] for symbol, rows in observations.items() if now in rows}
        trades = []
        for symbol, bar in sorted(present.items()):
            sequence += 1
            trades.append(dict(sequence=sequence, time=now.isoformat(), price=float(bar["open"]), symbol=symbol, contract_id=contracts[symbol]))
            if symbol in previous and now-previous[symbol] > pd.Timedelta(minutes=1):
                for position in list(state["positions"]):
                    if position["exposure"]["symbol"] == symbol:
                        position["pending_exit"] = "Data gap / next observed open"
            previous[symbol] = now
        known = {symbol: frame.loc[frame["time"] < now].copy() for symbol, frame in frames.items()}
        state = advance_portfolio(state, [], trades, policy, now.isoformat(), contracts=contracts,
                                  session_allowed=schedule["allow_entry"], session_reason=schedule["reason"], flatten=schedule["flatten"], management_histories=known)
        prices = {symbol: float(bar["open"]) for symbol, bar in present.items()}
        candidates, waits = (candidate_source(known, prices, contracts, now, policy, account=state["account"], profile="research")
                             if candidate_source else candidates_at(known, prices, contracts, now, policy,
                                account=state["account"], profile="research", configurations=configurations))
        state["data_rejections"].extend(waits)
        from goxtrade.research.managed_positions import with_exit_policy
        candidates = with_exit_policy(candidates, profit_policy)
        state = advance_portfolio(state, candidates, [], policy, now.isoformat(), contracts=contracts,
                                  session_allowed=schedule["allow_entry"], session_reason=schedule["reason"])
        closed_at = now+pd.Timedelta(minutes=1)
        for symbol, bar in present.items():
            state["marks"][symbol] = dict(price=float(bar["close"]), time=closed_at.isoformat(), contract_id=contracts[symbol])
            for position in list(state["positions"]):
                if position["exposure"]["symbol"] != symbol:
                    continue
                if position.get("trade_management"):
                    from goxtrade.research.managed_positions import completed_bar
                    full_known = frames[symbol].loc[frames[symbol]["time"] <= now].copy()
                    completed_bar(state, position, bar, full_known, closed_at)
                    continue
                exposure, candidate = position["exposure"], position["candidate"]
                long = candidate["direction"] == "LONG"
                stop = float(bar["low"]) <= exposure["stop"] if long else float(bar["high"]) >= exposure["stop"]
                target = float(bar["high"]) >= candidate["target"] if long else float(bar["low"]) <= candidate["target"]
                fixed = candidate["management_mode"] not in ("structure-v1", "trailing")
                if stop or (target and fixed):
                    price = (min(float(bar["open"]), exposure["stop"]) if long else max(float(bar["open"]), exposure["stop"])) if stop else candidate["target"]
                    close_position(state, position, price, closed_at, "Stop first / ambiguous OHLC" if stop and target and fixed else "Stop" if stop else "Target", bool(stop and target and fixed))
            full = frames[symbol].loc[frames[symbol]["time"] <= now].copy()
            full.attrs.update(frames[symbol].attrs)
            manage_completed(state, symbol, full, closed_at)
        marked = state["realized"]
        for position in state["positions"]:
            exposure = position["exposure"]
            marked += (state["marks"][exposure["symbol"]]["price"]-exposure["entry"])*(1 if exposure["direction"] == "LONG" else -1)*instrument(exposure["symbol"]).point_value*exposure["quantity"]
            marked -= position["policy"]["commission_per_side"]*exposure["quantity"]
        state["equity"].append(marked)
    return dict(kind="portfolio_backtest", policy=policy.to_dict(), profit_policy=profit_policy.to_dict() if profit_policy else None, configurations=configurations or {}, datasets=hashes,
                summary=portfolio_summary(state), state=state, broker_checks="NOT_PERFORMED", assumptions="Next observed open; stop first for ambiguous OHLC; gaps marked; no synthetic rollover")


def compare_portfolios(datasets, policy, configurations=None, *, profit_policy=None):
    scenarios = {name: replace(policy, mode=name) for name in ("conservative", "first_confirmed", "configured_priority")}
    scenarios.update({"individual:"+key: replace(policy, participating=(key,)) for key in policy.participating})
    return {name: run_portfolio_backtest(datasets, settings, configurations, profit_policy=profit_policy) for name, settings in scenarios.items()}


def walk_forward(datasets, policy, configurations=None, folds=3, *, profit_policy=None):
    if type(folds) is not int or not 2 <= folds <= 10:
        raise ValueError("Use 2-10 chronological out-of-sample folds")
    times = sorted(set().union(*(set(pd.to_datetime(frame["time"], utc=True)) for _, _, frame in datasets)))
    if len(times) < folds*30:
        raise ValueError("Insufficient real observations for chronological folds")
    # Prespecified policy, never fitted using test outcomes. Warmup remains causal.
    results = []
    for fold in range(1, folds):
        end = times[(fold+1)*len(times)//folds-1]
        start = times[fold*len(times)//folds]
        def source(known, prices, contracts, now, settings, **kwargs):
            return candidates_at(known, prices, contracts, now, settings, configurations=configurations, **kwargs) if now >= start else ([], [])
        sliced = [(symbol, contract, frame.loc[pd.to_datetime(frame["time"], utc=True) <= end].copy()) for symbol, contract, frame in datasets]
        result = run_portfolio_backtest(sliced, policy, configurations, candidate_source=source, profit_policy=profit_policy)
        results.append(dict(test_start=start.isoformat(), test_end=end.isoformat(), policy_fitted=False, result=result))
    return results
