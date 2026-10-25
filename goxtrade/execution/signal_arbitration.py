"""Stable policy preferences, not AI confidence or invented performance rankings."""
from goxtrade.execution.trade_candidate import stamp


def priority_key(candidate, policy):
    priority = policy.priority.index(candidate.strategy_id) if candidate.strategy_id in policy.priority else 10000
    if policy.mode == "first_confirmed":
        return stamp(candidate.confirmed_at), priority, candidate.candidate_id
    return priority, stamp(candidate.confirmed_at), candidate.candidate_id


def arbitrate(candidates, policy):
    groups, selected, blocked, supporting = {}, [], {}, {}
    for candidate in candidates:
        groups.setdefault(candidate.exposure, []).append(candidate)
    for values in groups.values():
        if len({c.direction for c in values}) > 1:
            for candidate in values:
                blocked[candidate.candidate_id] = tuple(c.candidate_id for c in values if c.direction != candidate.direction)
            continue
        winner = min(values, key=lambda c: priority_key(c, policy))
        selected.append(winner)
        supporting[winner.candidate_id] = tuple(c.candidate_id for c in sorted(values, key=lambda c: c.candidate_id) if c != winner)
        for candidate in values:
            if candidate != winner:
                blocked[candidate.candidate_id] = (winner.candidate_id,)
    return sorted(selected, key=lambda c: priority_key(c, policy)), blocked, supporting
