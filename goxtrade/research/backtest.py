"""Causal single-contract simulation. This module has no broker dependency."""
from dataclasses import asdict, dataclass, replace
import math
import hashlib

import pandas as pd

from goxtrade.market.instruments import instrument
from goxtrade.market.market_session import market_session
from goxtrade.market.trading_schedule import execution_schedule
from goxtrade.research.adapters import legacy_candidate
from goxtrade.research.datasets import UnsupportedDataset, dataset_hash, validate_dataset, validate_ticks
from goxtrade.research.metrics import statistics, breakdown, monthly_returns
from goxtrade.strategies.adaptive_exit import MODE, update_exit
from goxtrade.strategies.stop_policy import aggregate_minutes
from goxtrade.strategies.strategy_catalog import strategy_spec
from goxtrade.strategies.vwap_ema_config import VwapEmaConfig
from goxtrade.strategies.vwap_ema_cross import evaluate_vwap_ema_cross


@dataclass(frozen=True)
class SimulationConfig:
    quantity: int = 1
    starting_balance: float = 50000.
    commission_per_side: float | None = None
    zero_cost_sensitivity: bool = False
    slippage_ticks: float = 1.
    cooldown_minutes: int = 0
    enforce_execution_schedule: bool = True
    rollover_policy: str = "single_contract"
    max_initial_risk_usd: float | None = None
    minimum_effective_rr: float = 0.

    def validate(self):
        if type(self.quantity) is not int or not 1 <= self.quantity <= 4:
            raise ValueError("Research quantity must be 1-4 contracts")
        if self.commission_per_side is None:
            raise ValueError("Enter a commission per contract/side; no fee is assumed")
        if type(self.zero_cost_sensitivity) is not bool or type(self.enforce_execution_schedule) is not bool:
            raise ValueError("Simulation switches must be true or false")
        if self.commission_per_side == 0 and not self.zero_cost_sensitivity:
            raise ValueError("Zero commission requires an explicit zero-cost sensitivity scenario")
        if any(type(value) not in (float, int) or not math.isfinite(value) or value < 0
               for value in (self.starting_balance, self.commission_per_side, self.slippage_ticks, self.cooldown_minutes, self.minimum_effective_rr)):
            raise ValueError("Simulation balances, costs, and cooldown must be finite and nonnegative")
        if self.slippage_ticks % 1 or type(self.cooldown_minutes) is not int:
            raise ValueError("Slippage uses whole ticks and cooldown uses whole minutes")
        if self.max_initial_risk_usd is not None and (type(self.max_initial_risk_usd) not in (float, int)
                or not math.isfinite(self.max_initial_risk_usd) or self.max_initial_risk_usd <= 0):
            raise ValueError("Research initial-risk cap must be finite and positive")
        return self


def fill_validation(signal, fill, symbol, sim):
    """Research-only validation; never changes account sizing or loss limits."""
    sign = 1 if signal.get("direction", signal.get("signal")) == "LONG" else -1
    risk = (fill-signal["stop"])*sign
    reward = (signal["target"]-fill)*sign
    dollars = risk*instrument(symbol).point_value*sim.quantity
    rr = reward/risk if risk > 0 else None
    reason = ("Fill invalidates stop/target geometry" if risk <= 0 or reward <= 0 else
              "Fill exceeds research initial-risk cap" if sim.max_initial_risk_usd is not None and dollars > sim.max_initial_risk_usd else
              "Fill falls below minimum effective RR" if rr < sim.minimum_effective_rr else None)
    return dict(valid=reason is None, reason=reason, initial_risk_usd=dollars if risk > 0 else None, effective_reward_risk=rr)


def closed_trade(active, exit_price, stamp, reason, symbol, spec, sim, ambiguous=False):
    contract = instrument(symbol)
    sign = 1 if active["signal"] == "LONG" else -1
    exit_fill = exit_price-sign*sim.slippage_ticks*contract.tick_size
    gross = (exit_fill-active["entry"])*sign*contract.point_value*sim.quantity
    costs = 2*sim.commission_per_side*sim.quantity
    risk = abs(active["entry"]-active["initial_stop"])*contract.point_value*sim.quantity
    return dict(strategy=spec.name, strategy_id=spec.id, symbol=contract.symbol,
                contract_id=active["contract_id"], timeframe=active["signal_minutes"],
                entry_mode=active.get("entry_mode", "CONFIRMED"), session=active["session"],
                direction=active["signal"], entry_time=active["entry_time"], exit_time=stamp.isoformat(),
                entry=active["entry"], exit=exit_fill, initial_stop=active["initial_stop"], target=active["target"],
                quantity=sim.quantity, gross=gross, costs=costs, net=gross-costs,
                reason=reason, ambiguous=ambiguous, r_multiple=(gross-costs)/risk if risk else None,
                holding_seconds=(stamp-pd.Timestamp(active["entry_time"])).total_seconds(),
                slippage_cost=2*sim.slippage_ticks*contract.tick_value*sim.quantity,
                unique_setup_id=active.get("unique_setup_id"), config_fingerprint=active.get("config_fingerprint"),
                crossover_key=active.get("crossover_key"), candle_time=active.get("candle_time"),
                source_contract=active.get("source_contract"), session_id=active.get("session_id"),
                fill_validation=active.get("fill_validation"),
                simulation_parameters=asdict(sim), test_type="historical_backtest")


def manage_after_close(active, bar, known, stamp):
    long = active["signal"] == "LONG"
    sign = 1 if long else -1
    if active.get("exit_mode") == MODE:
        rows = [{**row, "time": row["time"].isoformat(),
                 "closed_at": (row["time"]+pd.Timedelta(minutes=1)).isoformat()} for row in known.to_dict("records")]
        bars = aggregate_minutes(rows, active.get("management_minutes", 1))
        return update_exit(active, bars, dict(event_time=stamp.isoformat()))
    risk = abs(active["entry"]-active["initial_stop"])
    favorable = (bar["close"]-active["entry"])*sign
    if active.get("exit_mode") == "breakeven" and favorable >= risk*active.get("breakeven_r", 1):
        active["stop"] = max(active["stop"], active["entry"]) if long else min(active["stop"], active["entry"])
    if active.get("exit_mode") == "trailing" and favorable >= risk*active.get("trail_start_r", 1.5):
        level = bar["close"]-sign*active["trail_ticks"]*active["tick_size"]
        active["stop"] = max(active["stop"], level) if long else min(active["stop"], level)
    return None


def run_backtest(minutes, symbol, contract_id, strategy="VWAP EMA Cross", strategy_config=None,
                 simulation=None, ticks=None, trade_start=None):
    sim = (simulation or SimulationConfig()).validate()
    from goxtrade.market.instruments import validate_contract_instrument
    validate_contract_instrument(symbol, contract_id)
    spec = strategy_spec(strategy)
    config = VwapEmaConfig.from_dict(strategy_config) if spec.id == "vwap_ema_cross" else None
    signal_symbol = instrument(symbol).symbol + "=F"
    if config:
        config = replace(config, monitor_enabled=True, enabled_symbols=(signal_symbol,))
    frame = validate_dataset(minutes, contract_id, sim.rollover_policy)
    tick = instrument(symbol).tick_size
    if ((frame[["open", "high", "low", "close"]]/tick).sub((frame[["open", "high", "low", "close"]]/tick).round()).abs() > 1e-6).any().any():
        raise UnsupportedDataset("OHLC prices do not match the selected instrument tick grid")
    if config and config.entry_mode != "CONFIRMED":
        return _tick_backtest(frame, validate_ticks(ticks, contract_id), signal_symbol, contract_id, spec, config, sim, trade_start)
    if ticks is not None:
        raise UnsupportedDataset("Use the intrabar modes to replay trade observations")
    start = max(pd.Timestamp(trade_start).tz_convert("UTC"), frame.iloc[0]["time"]) if trade_start is not None else frame.iloc[0]["time"]
    if start >= frame.iloc[-1]["time"]+pd.Timedelta(minutes=1):
        raise ValueError("No observations in the requested trading window")
    contract = instrument(symbol)
    slip = sim.slippage_ticks*contract.tick_size
    observation, seen, active, pending_exit = {}, set(), None, None
    next_entry = start
    trades, decisions, equity = [], {}, [sim.starting_balance]
    balance = sim.starting_balance
    gap_exits = 0
    evaluated_bucket = None
    for index, bar in enumerate(frame.to_dict("records")):
        now = bar["time"]
        schedule = execution_schedule(now.to_pydatetime(), calendar=False)
        gap = index > 0 and now-frame.iloc[index-1]["time"] > pd.Timedelta(minutes=1)
        if active and (pending_exit or (sim.enforce_execution_schedule and schedule["flatten"]) or gap):
            reason = pending_exit or ("Data gap / next observed open" if gap else "Scheduled flatten / next available open")
            trade = closed_trade(active, bar["open"], now, reason, symbol, spec, sim, ambiguous=gap)
            trades.append(trade)
            balance += trade["net"]
            gap_exits += int(gap)
            active, pending_exit = None, None
            next_entry = now+pd.Timedelta(minutes=sim.cooldown_minutes)
        known = frame.iloc[:index]
        raw = dict(signal="WAIT")
        bucket = now.floor(f"{config.signal_minutes if config else spec.signal_minutes}min")
        if index and now >= start and bucket != evaluated_bucket:
            evaluated_bucket = bucket
            if config:
                raw, _, observation = evaluate_vwap_ema_cross(known, bar["open"], now, config,
                                                              observation, historical=True, symbol=signal_symbol)
            else:
                raw = legacy_candidate(known, bar["open"], now, symbol, spec.name, strategy_config)
        event = raw.get("unique_setup_id")
        direction = raw.get("direction", raw.get("signal"))
        new = direction in ("LONG", "SHORT") and event not in seen
        if event:
            seen.add(event)
        allow = market_session(now.to_pydatetime())["is_open"] and (not sim.enforce_execution_schedule or schedule["allow_entry"])
        if active is None and new and allow and now >= next_entry:
            sign = 1 if direction == "LONG" else -1
            fill = bar["open"]+sign*slip
            validation = fill_validation(raw, fill, symbol, sim)
            if validation["valid"]:
                active = {**raw, "signal": direction, "entry": fill, "initial_stop": raw["stop"],
                          "fill_validation": validation,
                          "entry_time": now.isoformat(), "management_started_at": now.isoformat(),
                          "session": market_session(now.to_pydatetime())["name"], "contract_id": contract_id}
            else:
                decisions[validation["reason"]] = decisions.get(validation["reason"], 0)+1
        elif new:
            reason = "Position already open" if active else "Execution session / cooldown"
            decisions[reason] = decisions.get(reason, 0)+1
        if active:
            long = active["signal"] == "LONG"
            stopped = bar["low"] <= active["stop"] if long else bar["high"] >= active["stop"]
            targeted = bar["high"] >= active["target"] if long else bar["low"] <= active["target"]
            fixed_target = active.get("exit_mode") not in (MODE, "trailing")
            closed_at = now+pd.Timedelta(minutes=1)
            if stopped or (targeted and fixed_target):
                price = (min(bar["open"], active["stop"]) if long else max(bar["open"], active["stop"])) if stopped else active["target"]
                ambiguous = bool(stopped and targeted and fixed_target)
                reason = "Stop first / ambiguous OHLC" if ambiguous else "Stop" if stopped else "Target"
                trade = closed_trade(active, price, closed_at, reason, symbol, spec, sim, ambiguous)
                trades.append(trade)
                balance += trade["net"]
                active = None
                next_entry = closed_at+pd.Timedelta(minutes=sim.cooldown_minutes)
            else:
                pending_exit = manage_after_close(active, bar, frame.iloc[:index+1], closed_at)
        marked = balance
        if active:
            marked += (bar["close"]-active["entry"])*(1 if active["signal"] == "LONG" else -1)*contract.point_value*sim.quantity
            marked -= sim.commission_per_side*sim.quantity
        equity.append(marked)
    return _result(frame, trades, decisions, active, spec, config, sim, equity, gap_exits, analysis_start=start)


def _result(frame, trades, decisions, active, spec, config, sim, equity, gap_exits=0, analysis_start=None, analysis_end=None):
    start = analysis_start if analysis_start is not None else frame.iloc[0]["time"]
    end = analysis_end if analysis_end is not None else frame.iloc[-1]["time"]+pd.Timedelta(minutes=1)
    duration = max(0., (end-start).total_seconds())
    open_fees = sim.commission_per_side*sim.quantity if active else 0.
    closed_net = sum(row["net"] for row in trades)
    return dict(strategy_id=spec.id, strategy=spec.name, test_type="historical_backtest", trades=trades,
                accounting=dict(closed_trade_net=closed_net, realized_balance=sim.starting_balance+closed_net-open_fees,
                                open_entry_commission=open_fees, marked_equity=equity[-1],
                                unrealized_pnl=equity[-1]-(sim.starting_balance+closed_net-open_fees)),
                monthly_returns=monthly_returns(trades, sim.starting_balance),
                summary=statistics(trades, sim.starting_balance, duration, equity),
                breakdown={key: breakdown(trades, key) for key in ("session", "symbol", "entry_mode", "month")},
                config=config.to_dict() if config else {}, simulation=asdict(sim),
                dataset_hash=dataset_hash(frame), contract_id=frame.attrs["contract_id"],
                contract_validation="ProjectX product matched" if frame.attrs["contract_id"].startswith("CON.F.US.") else "Caller-declared provider contract; not independently verified",
                provenance=frame.attrs.get("provenance", "Caller-supplied OHLCV; source not independently verified"),
                warmup_start=frame.iloc[0]["time"].isoformat(), start=start.isoformat(), end=end.isoformat(),
                open_at_end=bool(active), open_position=active, decisions=decisions,
                ambiguous_trades=sum(row["ambiguous"] for row in trades), data_gap_exits=gap_exits,
                limitations=["Single contract; no synthetic continuous-contract rollover.",
                             "Trade prices plus adverse slippage model executable fills; bid/ask depth and queue are unavailable.",
                             "OHLC stop/target collisions use stop first; structure exits fill at the next available open.",
                             "Open end positions are excluded from realized totals; drawdown includes available marked equity.",
                             "Legacy adapters preserve signal rules but do not emulate account-specific broker or overnight preflight.",
                             "Historical samples do not establish profitability or future execution quality."])


def _tick_backtest(minutes, ticks, symbol, contract_id, spec, config, sim, trade_start):
    """Observation replay: detect on one trade, fill only on a later sequence."""
    if ticks.empty:
        raise UnsupportedDataset("No intrabar observations available")
    start = max(pd.Timestamp(trade_start).tz_convert("UTC"), ticks.iloc[0]["time"]) if trade_start is not None else ticks.iloc[0]["time"]
    if start > ticks.iloc[-1]["time"]:
        raise ValueError("No trade observations in the requested trading window")
    contract = instrument(symbol)
    observation, pending, active, seen = {}, None, None, set()
    if ((ticks["price"]/contract.tick_size)-(ticks["price"]/contract.tick_size).round()).abs().gt(1e-6).any():
        raise UnsupportedDataset("Trade prices do not match the selected instrument tick grid")
    trades, decisions, partials, equity = [], {}, {}, [sim.starting_balance]
    balance = sim.starting_balance
    next_entry = start
    for row in ticks.to_dict("records"):
        now, price, sequence = row["time"], float(row["price"]), int(row["sequence"])
        minute = now.floor("min")
        part = partials.setdefault(minute, dict(time=minute, open=price, high=price, low=price, close=price, volume=0.))
        part.update(high=max(part["high"], price), low=min(part["low"], price), close=price,
                    volume=part["volume"]+row["volume"], last_sequence=sequence, asof_time=now.isoformat())
        known = minutes.loc[minutes["time"]+pd.Timedelta(minutes=1) <= now]
        bucket = now.floor(f"{config.signal_minutes}min")
        snapshot = pd.concat([known.loc[known["time"] < bucket],
                              pd.DataFrame([value for stamp, value in partials.items() if stamp >= bucket])], ignore_index=True)
        snapshot.attrs.update(minutes.attrs)
        schedule = execution_schedule(now.to_pydatetime(), calendar=False)
        if active:
            long = active["signal"] == "LONG"
            stopped = price <= active["stop"] if long else price >= active["stop"]
            targeted = price >= active["target"] if long else price <= active["target"]
            reason = "Scheduled flatten" if sim.enforce_execution_schedule and schedule["flatten"] else "Stop" if stopped else "Target" if targeted and active.get("exit_mode") not in (MODE, "trailing") else None
            if not reason:
                reason = manage_after_close(active, dict(close=price), known, now)
                if price <= active["stop"] if long else price >= active["stop"]:
                    reason = reason or "New protective stop crossed at current trade"
            if reason:
                trade = closed_trade(active, price, now, reason, symbol, spec, sim)
                trades.append(trade)
                balance += trade["net"]
                active = None
                next_entry = now+pd.Timedelta(minutes=sim.cooldown_minutes)
        if pending and active is None and sequence > pending["detection_sequence"]:
            sign = 1 if pending["direction"] == "LONG" else -1
            fill = price+sign*sim.slippage_ticks*contract.tick_size
            eligible = (now-pd.Timestamp(pending["detected_at"])).total_seconds() < config.entry_window_seconds
            eligible &= not sim.enforce_execution_schedule or schedule["allow_entry"]
            if eligible and now >= next_entry:
                validation = fill_validation(pending, fill, symbol, sim)
                active = {**pending, "signal": pending["direction"], "entry": fill,
                          "fill_validation": validation,
                          "initial_stop": pending["stop"], "entry_time": now.isoformat(),
                          "management_started_at": now.isoformat(), "contract_id": contract_id,
                          "session": market_session(now.to_pydatetime())["name"]}
                breached = price <= active["stop"] if sign == 1 else price >= active["stop"]
                reached = price >= active["target"] if sign == 1 else price <= active["target"]
                if not validation["valid"] or breached or (reached and active.get("exit_mode") not in (MODE, "trailing")):
                    trade = closed_trade(active, price, now, "Immediate protection after next-trade fill / "+str(validation["reason"] or "level crossed"), symbol, spec, sim)
                    trades.append(trade)
                    balance += trade["net"]
                    active = None
                    next_entry = now+pd.Timedelta(minutes=sim.cooldown_minutes)
            pending = None
        signal, _, observation = evaluate_vwap_ema_cross(snapshot, price, now, config, observation,
                                                         sequence=sequence, quote_time=now, symbol=symbol)
        event = signal.get("unique_setup_id")
        if event and event not in seen:
            seen.add(event)
            if active is None and pending is None and now >= max(start, next_entry) and market_session(now.to_pydatetime())["is_open"]:
                estimated = price+(1 if signal["direction"] == "LONG" else -1)*sim.slippage_ticks*contract.tick_size
                validation = fill_validation(signal, estimated, symbol, sim)
                if validation["valid"]:
                    pending = signal
                else:
                    decisions[validation["reason"]] = decisions.get(validation["reason"], 0)+1
        equity.append(balance + ((price-active["entry"])*(1 if active["signal"] == "LONG" else -1)*contract.point_value*sim.quantity-sim.commission_per_side*sim.quantity if active else 0))
    result = _result(minutes, trades, decisions, active, spec, config, sim, equity,
                     analysis_start=start, analysis_end=ticks.iloc[-1]["time"])
    result["tick_dataset_hash"] = hashlib.sha256(ticks.to_csv(index=False, float_format="%.12g").encode()).hexdigest()
    result["pending_at_end"] = bool(pending)
    result["tick_observations"] = len(ticks)
    result["limitations"].append("Intrabar replay assumes the supplied file contains every trade in its declared observation window.")
    return result


def chronological_splits(minutes, symbol, contract_id, strategy="VWAP EMA Cross", strategy_config=None,
                         simulation=None, training_fraction=.7, folds=1, trade_start=None):
    """Expanding chronological training windows; no parameter selection by P&L."""
    if not .1 <= training_fraction <= .9 or type(folds) is not int or not 1 <= folds <= 10:
        raise ValueError("Choose a 10-90% initial training window and 1-10 folds")
    frame = validate_dataset(minutes, contract_id)
    offset = int(frame["time"].lt(pd.Timestamp(trade_start).tz_convert("UTC")).sum()) if trade_start is not None else 0
    split = offset+int((len(frame)-offset)*training_fraction)
    step = max(1, (len(frame)-split)//folds)
    runs = []
    for fold in range(folds):
        boundary = split+fold*step
        end = len(frame) if fold == folds-1 else min(len(frame), boundary+step)
        if boundary < 2 or boundary >= end:
            continue
        train = run_backtest(frame.iloc[:boundary], symbol, contract_id, strategy, strategy_config, simulation, trade_start=trade_start)
        test = run_backtest(frame.iloc[:end], symbol, contract_id, strategy, strategy_config, simulation,
                            trade_start=frame.iloc[boundary]["time"])
        runs.append(dict(fold=fold+1, split_at=frame.iloc[boundary]["time"].isoformat(), in_sample=train, out_of_sample=test))
    return runs
