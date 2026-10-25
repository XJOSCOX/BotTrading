"""Shared research policy and read-only profit diagnostics; no broker transport."""
from contextlib import closing
import json

from goxtrade.data.live_store import connect
from goxtrade.execution.profit_policy import ProfitPolicy
from goxtrade.execution.trade_candidate import digest, frozen_json
from goxtrade.execution.trade_analytics import analytics


def schema(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS profit_policy (id INTEGER PRIMARY KEY CHECK(id=1),record TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS profit_research_runs (id TEXT PRIMARY KEY,record TEXT NOT NULL)")


def read_policy():
    with closing(connect()) as conn:
        schema(conn)
        row = conn.execute("SELECT record FROM profit_policy WHERE id=1").fetchone()
    return ProfitPolicy.from_dict(json.loads(row[0])) if row else ProfitPolicy()


def save_policy(values):
    policy = ProfitPolicy.from_dict(values)
    with closing(connect()) as conn:
        schema(conn)
        conn.execute("INSERT INTO profit_policy VALUES(1,?) ON CONFLICT(id) DO UPDATE SET record=excluded.record", (frozen_json(policy.to_dict()),))
        conn.commit()
    return policy


def save_comparison(result):
    identifier = digest(result)
    with closing(connect()) as conn:
        schema(conn)
        conn.execute("INSERT OR IGNORE INTO profit_research_runs VALUES (?,?)", (identifier, frozen_json(result)))
        conn.commit()
    return identifier


def view(profile="practice"):
    from goxtrade.api.state import snapshot
    from goxtrade.bot.bot_health import snapshot as health
    from goxtrade.config.execution_identity import TARGETS
    if profile not in TARGETS:
        raise ValueError("Unknown profile")
    data = snapshot()["profiles"][profile]
    broker = health(data["broker"], account_id=TARGETS[profile]["gate_id"])
    broker_rows = []
    for job in data["jobs"]:
        if job.get("state") not in ("Open", "Closing", "Submitted", "Unknown", "Intent"):
            continue
        stops = [order for order in broker.get("orders", []) if order.get("parentOrderId") == job.get("order_id") and order.get("type") == 4 and order.get("contractId") == job.get("contract_id") and order.get("size") == job.get("filled_quantity")]
        broker_rows.append(dict(strategy=job.get("strategy"), symbol=job.get("symbol"), entry=job.get("fill_price"), quantity=job.get("filled_quantity"),
                                broker_stop=stops[0].get("stopPrice") if len(stops) == 1 else None,
                                protection="Reported broker stop / verify freshness" if len(stops) == 1 else "Not verified / review broker",
                                source="Broker job / legacy policy; no policy migration", broker_observed_at=broker.get("updated_at"),
                                mfe=None, giveback=None))
    paper, closed, runs = [], [], []
    with closing(connect()) as conn:
        schema(conn)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "manager_simulation" in tables:
            for row in conn.execute("SELECT record FROM manager_simulation WHERE kind='portfolio_forward_paper'"):
                state = json.loads(row[0])["state"]
                paper.extend({**position["trade_management"], "population":"Portfolio paper"} for position in state["positions"] if position.get("trade_management"))
                closed.extend({**trade, "population":"Portfolio paper"} for trade in state["trades"] if trade.get("management_analytics"))
        if "strategy_paper_states" in tables:
            for row in conn.execute("SELECT record FROM strategy_paper_states"):
                active = json.loads(row[0]).get("active") or {}
                if active.get("trade_management"):
                    paper.append({**active["trade_management"], "population":"Strategy paper"})
        if "strategy_paper_trades" in tables:
            closed.extend({**json.loads(row[0]), "population":"Strategy paper"} for row in conn.execute("SELECT record FROM strategy_paper_trades") if json.loads(row[0]).get("management_analytics"))
        runs = [dict(id=row[0], result=json.loads(row[1])) for row in conn.execute("SELECT id,record FROM profit_research_runs ORDER BY rowid DESC LIMIT 20")]
    return dict(policy=read_policy().to_dict(), profile=profile, broker_positions=broker_rows,
                paper_positions=[{**position, "analytics":analytics(position)} for position in paper],
                paper_closed=closed[-200:], comparisons=runs, broker_changes_enabled=False)
