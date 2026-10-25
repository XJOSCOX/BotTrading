"""Prespecified policies compete against one frozen causal candidate tape."""
from collections import defaultdict
import pandas as pd

from goxtrade.execution.profit_policy import comparison_policies
from goxtrade.execution.trade_candidate import digest
from goxtrade.research.portfolio_backtest import run_portfolio_backtest, candidates_at


def diagnostics(result):
    trades = result["state"]["trades"]
    rows = [row["management_analytics"] for row in trades if row.get("management_analytics")]
    def average(key):
        values = [row[key] for row in rows if row.get(key) is not None]
        return sum(values)/len(values) if values else None
    return dict(average_mfe=average("mfe_dollars"), average_mae=average("mae_dollars"),
                average_profit_captured=average("capture_percent"), average_giveback=average("profit_giveback"),
                average_seconds_peak_to_exit=average("seconds_peak_to_exit"),
                flagged_trades=sum(bool(row["diagnostic_categories"]) for row in rows),
                groups={key: {name:dict(trades=len(values), net=sum(row["net"] for row in values),
                    average_giveback=sum(row.get("management_analytics", {}).get("profit_giveback", 0) for row in values)/len(values))
                    for name, values in _group(trades, key).items()} for key in ("strategy", "symbol", "session")})


def _group(rows, key):
    result = defaultdict(list)
    for row in rows:
        result[row.get(key, "unknown")].append(row)
    return result


def compare_exits(datasets, execution_policy, configurations=None, *, candidate_source=None, trade_start=None, progress=None):
    tape = {}
    def record(histories, prices, contracts, now, policy, **identity):
        if trade_start is not None and now < pd.Timestamp(trade_start):
            tape[now.isoformat()] = ([], [])
        else:
            tape[now.isoformat()] = (candidate_source(histories, prices, contracts, now, policy, **identity)
                                    if candidate_source else candidates_at(histories, prices, contracts, now, policy, configurations=configurations, **identity))
        return tape[now.isoformat()]
    policies = comparison_policies()
    baseline = run_portfolio_backtest(datasets, execution_policy, configurations, candidate_source=record, profit_policy=policies["baseline"], progress=(lambda value:progress(value/10)) if progress else None)
    results = {"baseline": baseline}
    def replay(histories, prices, contracts, now, policy, **identity):
        return tape[now.isoformat()]
    for index, (name, policy) in enumerate(policies.items()):
        if name != "baseline":
            results[name] = run_portfolio_backtest(datasets, execution_policy, configurations, candidate_source=replay, profit_policy=policy, progress=(lambda value,i=index:progress((i+value)/10)) if progress else None)
    signals = {time:[candidate.to_dict() for candidate in value[0]] for time, value in tape.items()}
    return dict(kind="exit_policy_comparison", candidate_tape_hash=digest(signals), candidate_events=sum(len(rows) for rows in signals.values()),
                policies={name:dict(summary=result["summary"], diagnostics=diagnostics(result), trades=result["state"]["trades"],
                                   open_positions=result["state"]["positions"], policy=policies[name].to_dict()) for name, result in results.items()},
                execution_policy=execution_policy.to_dict(), datasets=baseline["datasets"],
                assumptions="Same observable candidate tape and costs; portfolio competition can change selected entries as exit times differ. No fitted policy ranking.",
                broker_checks="NOT_PERFORMED")


def chronological_exit_folds(datasets, execution_policy, configurations=None, folds=3):
    if type(folds) is not int or not 2 <= folds <= 5:
        raise ValueError("Use 2-5 prespecified chronological exit-policy folds")
    times = sorted(set().union(*(set(pd.to_datetime(frame["time"], utc=True)) for _, _, frame in datasets)))
    if len(times) < folds*30:
        raise ValueError("Insufficient actual observations for exit-policy folds")
    results = []
    for fold in range(1, folds):
        start, end = times[fold*len(times)//folds], times[(fold+1)*len(times)//folds-1]
        sliced = [(symbol, contract, frame.loc[pd.to_datetime(frame["time"], utc=True) <= end].copy()) for symbol, contract, frame in datasets]
        result = compare_exits(sliced, execution_policy, configurations, trade_start=start)
        results.append(dict(test_start=start.isoformat(), test_end=end.isoformat(), parameters_fitted=False,
                            policies={name:dict(summary=row["summary"], diagnostics=row["diagnostics"]) for name,row in result["policies"].items()}))
    return results
