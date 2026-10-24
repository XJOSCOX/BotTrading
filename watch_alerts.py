"""User dismissal of untraded signals, serialized with execution claims."""
import json
from contextlib import closing
from datetime import datetime, timezone
from live_store import connect


def clear_watch_alerts(alert_ids):
    cleared = 0
    with closing(connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        for alert_id in set(alert_ids):
            owned = False
            for profile in ("leader","practice"):
                if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?",(profile+"_jobs",)).fetchone():
                    job = conn.execute(f"SELECT record FROM {profile}_jobs WHERE alert_id=?",(alert_id,)).fetchone()
                    if job and json.loads(job[0]).get("state") not in ("Closed", "Rejected"):
                        owned = True
            if owned:
                continue
            row = conn.execute("SELECT record FROM bot_alert_history WHERE id=?",(alert_id,)).fetchone()
            if not row:
                continue
            record = json.loads(row[0])
            if record.get("status") != "Active":
                continue
            record.update(status="Dismissed",dismissed_at=datetime.now(timezone.utc).isoformat(),exit_reason="Watch cleared by user")
            conn.execute("UPDATE bot_alert_history SET record=? WHERE id=?",(json.dumps(record),alert_id))
            state_row = conn.execute("SELECT state FROM signal_lifecycle WHERE symbol=? AND strategy=?",(record["symbol"],record["strategy"])).fetchone()
            if state_row:
                state = json.loads(state_row[0])
                if state.get("event_id") == alert_id:
                    state.update(active=None,event_id=None,exit="Watch cleared by user")
                    conn.execute("UPDATE signal_lifecycle SET state=? WHERE symbol=? AND strategy=?",(json.dumps(state),record["symbol"],record["strategy"]))
            cleared += 1
        conn.commit()
    return cleared
