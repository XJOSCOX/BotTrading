"""Keep broker, forward-paper, and historical populations explicitly separate."""
import pandas as pd

from goxtrade.research.metrics import statistics


TYPES = ("historical_backtest", "forward_paper", "broker_practice", "leader")


def broker_trades(profile):
    from goxtrade.execution.executed_results import results
    from goxtrade.bot.signal_lifecycle import alert_history
    if profile == "leader":
        from goxtrade.execution import leader_execution
        _, _, jobs = leader_execution.snapshot()
        _, fills = leader_execution.history()
    elif profile == "practice":
        from goxtrade.execution import practice_executor, practice_history
        _, _, jobs = practice_executor.snapshot()
        _, fills = practice_history.snapshot()
    else:
        raise ValueError("Unknown account results population")
    signals = {row["id"]: row for row in alert_history(10000)}
    matched = results(jobs, fills)
    trades = []
    for job in jobs:
        value = matched.get(job["alert_id"])
        if value is None:
            continue
        signal = signals.get(job["alert_id"], {})
        entries = [fill for fill in fills if fill.get("orderId") == job.get("order_id") and not fill.get("voided")]
        entry_time = min((fill["creationTimestamp"] for fill in entries), default=None)
        held = (pd.Timestamp(value["closed_at"])-pd.Timestamp(entry_time)).total_seconds() if entry_time else 0
        from goxtrade.market.market_session import market_session
        session = market_session(pd.Timestamp(entry_time).to_pydatetime())["name"] if entry_time else "Unknown"
        trades.append({**value, "strategy": signal.get("strategy", job.get("strategy", "Unknown")),
                       "strategy_id": signal.get("strategy_id", job.get("strategy_id")),
                       "symbol": job["symbol"], "direction": signal.get("signal", "Unknown"),
                       "entry_mode": signal.get("entry_mode", "CONFIRMED"),
                       "timeframe": signal.get("signal_minutes", 15), "quantity": job["quantity"],
                       "entry_time": entry_time, "exit_time": value["closed_at"], "holding_seconds": held,
                       "test_type": "leader" if profile == "leader" else "broker_practice",
                       "session": session, "order_id": job.get("order_id"),
                       "comparison_context": f"{profile} / account {job.get('account_id', '--')} / {job['contract_id']} / qty {job['quantity']} / actual fills and reported costs"})
    return trades


def population(test_type):
    if test_type not in TYPES:
        raise ValueError("Unknown results population")
    if test_type == "historical_backtest":
        from goxtrade.research.result_store import saved_runs
        rows = []
        for run in saved_runs():
            result = run["result"]
            sim = result["simulation"]
            context = (f"Run #{run['id']} / OHLCV {result['dataset_hash'][:12]} / ticks {result.get('tick_dataset_hash', '--')[:12]} / "
                       f"{result['start']} to {result['end']} / qty {sim['quantity']} / fee-side {sim['commission_per_side']} / slip {sim['slippage_ticks']} ticks")
            rows.extend({**row, "run_id": run["id"], "comparison_context": context} for row in result["trades"])
        return rows
    if test_type == "forward_paper":
        from goxtrade.research.forward_paper import paper_trades
        return [{**row, "comparison_context": f"{row['contract_id']} / qty {row['quantity']} / config {row.get('config_fingerprint', '--')} / simulated costs {row.get('simulation_parameters', {})}"} for row in paper_trades()]
    return broker_trades("leader" if test_type == "leader" else "practice")


def comparison(rows, symbol=None, strategy=None, session=None, timeframe=None, start=None, end=None):
    filtered = [row for row in rows if (symbol is None or row["symbol"] == symbol)
                and (strategy is None or row["strategy"] == strategy)
                and (session is None or row.get("session") == session)
                and (timeframe is None or row.get("timeframe") == timeframe)
                and (start is None or pd.Timestamp(row["exit_time"]) >= pd.Timestamp(start))
                and (end is None or pd.Timestamp(row["exit_time"]) < pd.Timestamp(end))]
    groups = {}
    for row in filtered:
        key = (row["test_type"], row["comparison_context"], row["strategy"], row.get("timeframe"), row.get("entry_mode"))
        groups.setdefault(key, []).append(row)
    output = []
    for (kind, context, name, interval, mode), values in groups.items():
        output.append(dict(strategy=name, test_type=kind, context=context, timeframe=interval, entry_mode=mode,
                           symbol=", ".join(sorted({row["symbol"] for row in values})),
                           sample_start=min(row.get("entry_time") or row["exit_time"] for row in values),
                           sample_end=max(row["exit_time"] for row in values),
                           **statistics(values)))
    return sorted(output, key=lambda row: (row["net"], row["trades"]), reverse=True)
