"""Last verified broker reconciliation, separate from worker heartbeat."""
from contextlib import closing
from datetime import datetime, timezone
import json
from live_store import connect
from execution_target import TARGET


def record(positions, orders, account_id=TARGET["gate_id"]):
    if not isinstance(positions, list) or not isinstance(orders, list):
        raise ValueError("Broker state missing")
    with closing(connect()) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS bot_health (id INTEGER PRIMARY KEY, record TEXT)")
        conn.execute("INSERT OR REPLACE INTO bot_health VALUES(?,?)", (account_id,json.dumps(dict(updated_at=datetime.now(timezone.utc).isoformat(),positions=positions,orders=orders,error=False))))
        conn.commit()


def snapshot(fallback=None, account_id=TARGET["gate_id"]):
    candidates = []
    if fallback and isinstance(fallback.get("positions"),list) and isinstance(fallback.get("orders"),list):
        candidates.append(fallback)
    with closing(connect()) as conn:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='bot_health'").fetchone():
            row = conn.execute("SELECT record FROM bot_health WHERE id=?",(account_id,)).fetchone()
            if row:
                candidates.append(json.loads(row[0]))
    return max(candidates,key=lambda item:item.get("updated_at", ""),default={})
