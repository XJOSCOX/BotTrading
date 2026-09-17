"""Conservative attribution of broker fills to bot entries, excluding smoke tests."""
from datetime import datetime


def ts(value):
    return datetime.fromisoformat(value).timestamp()


def results(jobs, fills):
    valid = sorted([f for f in fills if not f.get("voided")], key=lambda f: (ts(f["creationTimestamp"]), f["id"]))
    output = {}
    for job in jobs:
        if job["alert_id"] < 0 or job["state"] != "Closed" or not job.get("closed_confirmed_at"):
            continue
        entries = [f for f in valid if f.get("orderId") == job.get("order_id")]
        if not entries or sum(f["size"] for f in entries) != job["quantity"]:
            continue
        start = min(ts(f["creationTimestamp"]) for f in entries)
        end = ts(job["closed_confirmed_at"])
        window = [f for f in valid if f["contractId"] == job["contract_id"] and start <= ts(f["creationTimestamp"]) <= end]
        exits = [f for f in window if f.get("side") == 1-job["side"]]
        if (any(f.get("side") == job["side"] and f.get("orderId") != job["order_id"] for f in window)
                or sum(f["size"] for f in exits) != job["quantity"]
                or any(f.get("profitAndLoss") is None for f in exits)):
            continue
        costs = sum((f.get("fees") or 0) + (f.get("commissions") or 0) for f in entries+exits)
        gross = sum(f["profitAndLoss"] for f in exits)
        output[job["alert_id"]] = dict(net=gross-costs, gross=gross, costs=costs,
                                      exit_price=sum(f["price"]*f["size"] for f in exits)/job["quantity"] if all(f.get("price") is not None for f in exits) else None,
                                      closed_at=max(f["creationTimestamp"] for f in exits))
    return output


def summary(matched):
    values = [r["net"] for r in matched.values()]
    return dict(wins=sum(v > 0 for v in values), losses=sum(v < 0 for v in values),
                breakeven=sum(v == 0 for v in values), win_rate=100*sum(v > 0 for v in values)/len(values) if values else None,
                won=sum(v for v in values if v > 0), lost=sum(v for v in values if v < 0), net=sum(values), missing=0)
