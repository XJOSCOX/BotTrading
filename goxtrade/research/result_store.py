"""Research results have their own tables and never enter broker P&L totals."""
from contextlib import closing
from datetime import datetime, timezone
import json

from goxtrade.data.live_store import connect


def save_run(config, result):
    if result.get("test_type") != "historical_backtest":
        raise ValueError("Only historical simulations can be saved as a backtest")
    with closing(connect()) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS strategy_research_runs (id INTEGER PRIMARY KEY,created_at TEXT NOT NULL,config TEXT NOT NULL,result TEXT NOT NULL)")
        cursor = conn.execute("INSERT INTO strategy_research_runs(created_at,config,result) VALUES (?,?,?)",
                              (datetime.now(timezone.utc).isoformat(), json.dumps(config, default=str), json.dumps(result, default=str)))
        conn.commit()
    return cursor.lastrowid


def saved_runs(limit=50):
    with closing(connect()) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='strategy_research_runs'").fetchone():
            return []
        return [dict(id=row[0], created_at=row[1], config=json.loads(row[2]), result=json.loads(row[3]))
                for row in conn.execute("SELECT * FROM strategy_research_runs ORDER BY id DESC LIMIT ?", (limit,))]
