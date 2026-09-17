"""Durable, deduplicated decisions and in-app notifications; no broker calls."""
import json
from contextlib import closing
from datetime import datetime, timezone
from live_store import connect
from execution_target import PROFILE


def init(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS bot_events (id INTEGER PRIMARY KEY, time TEXT, topic TEXT, alert_id INTEGER, kind TEXT, detail TEXT, severity TEXT, unread INTEGER)")
    conn.execute("CREATE INDEX IF NOT EXISTS bot_events_alert ON bot_events(alert_id,id)")
    conn.execute("CREATE TABLE IF NOT EXISTS bot_event_last (topic TEXT PRIMARY KEY, fingerprint TEXT)")


def emit(topic, kind, detail, alert_id=None, severity="info", notify=False, conn=None):
    if conn is None:
        with closing(connect()) as connection:
            emit(topic, kind, detail, alert_id, severity, notify, connection)
            connection.commit()
        return
    if PROFILE == "leader":
        topic = "leader:"+topic
        detail = "Leader / "+str(detail)
    init(conn)
    fingerprint = json.dumps([kind, detail, severity], sort_keys=True)
    prior = conn.execute("SELECT fingerprint FROM bot_event_last WHERE topic=?", (topic,)).fetchone()
    if prior and prior[0] == fingerprint:
        return
    conn.execute("INSERT INTO bot_events(time,topic,alert_id,kind,detail,severity,unread) VALUES(?,?,?,?,?,?,?)",
                 (datetime.now(timezone.utc).isoformat(), topic, alert_id, kind, str(detail), severity, int(notify)))
    conn.execute("INSERT OR REPLACE INTO bot_event_last VALUES(?,?)", (topic, fingerprint))


def events(limit=200, alert_id=None, unread=False, account="practice"):
    with closing(connect()) as conn:
        init(conn)
        where, args = ["topic LIKE 'leader:%'" if account == "leader" else "topic NOT LIKE 'leader:%'"], []
        if alert_id is not None:
            where.append("alert_id=?")
            args.append(alert_id)
        if unread:
            where.append("unread=1")
        clause = " WHERE " + " AND ".join(where) if where else ""
        return [dict(r) for r in conn.execute("SELECT * FROM bot_events" + clause + " ORDER BY id DESC LIMIT ?", (*args, limit))]


def entry_decisions(alert_ids, account="practice"):
    output = {}
    ids = list(dict.fromkeys(alert_ids))
    with closing(connect()) as conn:
        init(conn)
        predicate = "topic LIKE 'leader:%'" if account == "leader" else "topic NOT LIKE 'leader:%'"
        for offset in range(0, len(ids), 500):
            batch = ids[offset:offset+500]
            marks = ",".join("?" for _ in batch)
            rows = conn.execute(f"SELECT * FROM bot_events WHERE {predicate} AND kind='Entry blocked' AND alert_id IN ({marks}) ORDER BY id DESC", batch)
            for row in rows:
                decisions = output.setdefault(row["alert_id"], [])
                if len(decisions) < 2:
                    decisions.append(dict(row))
    return output


def acknowledge(through_id, account="practice"):
    with closing(connect()) as conn:
        init(conn)
        predicate = "topic LIKE 'leader:%'" if account == "leader" else "topic NOT LIKE 'leader:%'"
        conn.execute("UPDATE bot_events SET unread=0 WHERE id<=? AND "+predicate, (int(through_id),))
        conn.commit()
