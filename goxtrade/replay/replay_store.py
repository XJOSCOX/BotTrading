"""Versioned replay-only database; optimistic commits fence competing controllers."""
from contextlib import closing
import json
import sqlite3
import uuid
from goxtrade.data import lab_store
from goxtrade.execution.trade_candidate import frozen_json


def connect():
    path = lab_store.database_path().with_name("offline_replay.db")
    path.parent.mkdir(parents=True,exist_ok=True)
    conn = sqlite3.connect(path,timeout=2)
    conn.row_factory=sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS replay_schema(version INTEGER PRIMARY KEY)")
    versions=[r[0] for r in conn.execute("SELECT version FROM replay_schema")]
    if versions and versions != [1]:
        conn.close()
        raise ValueError("Unsupported replay schema; saved state preserved")
    conn.execute("INSERT OR IGNORE INTO replay_schema VALUES(1)")
    conn.execute("CREATE TABLE IF NOT EXISTS replay_sessions(id TEXT PRIMARY KEY,revision INTEGER NOT NULL,record TEXT NOT NULL)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS replay_one_player ON replay_sessions((1)) WHERE json_extract(record,'$.status')='playing'")
    conn.execute("CREATE TABLE IF NOT EXISTS replay_ticks(id TEXT PRIMARY KEY,record TEXT NOT NULL)")
    conn.commit()
    return conn


def identifier(value):
    if not isinstance(value,str) or not value.startswith("replay-") or len(value)!=39:
        raise ValueError("An isolated replay identity is required, never a broker account ID")
    return value


def create(record):
    record={**record,"id":"replay-"+uuid.uuid4().hex,"revision":0}
    with closing(connect()) as conn:
        conn.execute("INSERT INTO replay_sessions VALUES(?,?,?)",(record["id"],0,frozen_json(record)))
        conn.commit()
    return record


def get(value):
    identifier(value)
    with closing(connect()) as conn:
        row=conn.execute("SELECT record FROM replay_sessions WHERE id=?",(value,)).fetchone()
    if not row:raise ValueError("Replay session not found")
    return json.loads(row[0])


def save(record):
    identifier(record["id"])
    old=record["revision"]
    updated={**record,"revision":old+1,"updated_at":lab_store.now()}
    with closing(connect()) as conn:
        try:
            changed=conn.execute("UPDATE replay_sessions SET revision=?,record=? WHERE id=? AND revision=?",
                                 (old+1,frozen_json(updated),record["id"],old)).rowcount
        except sqlite3.IntegrityError:
            raise ValueError("Pause the other replay session before starting playback; only one playback owns processing") from None
        if changed!=1:raise ValueError("Replay changed in another controller; reload before continuing")
        conn.commit()
    return updated


def summaries():
    with closing(connect()) as conn:
        rows=conn.execute("SELECT id,revision,json_extract(record,'$.status') status,json_extract(record,'$.clock') clock,json_extract(record,'$.updated_at') updated_at FROM replay_sessions ORDER BY rowid DESC LIMIT 50").fetchall()
    return [dict(r) for r in rows]


def ticks(identifier):
    with closing(connect()) as conn:
        row=conn.execute("SELECT record FROM replay_ticks WHERE id=?",(identifier,)).fetchone()
    if not row:raise ValueError("Actual recorded tick snapshot not found")
    return json.loads(row[0])
