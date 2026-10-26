"""Additive, durable Practice-test records. No network calls or startup side effects."""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from goxtrade.data import live_store


class TestBlocked(ValueError):
    """Safe operator-facing reason; never wrap raw broker responses."""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()).hexdigest()


class TestStore:
    def __init__(self, path=None):
        self.path = Path(path).resolve() if path else live_store.DB_PATH

    @contextmanager
    def transaction(self):
        with closing(sqlite3.connect(self.path, timeout=5)) as conn:
            conn.row_factory = sqlite3.Row
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS practice_test_reviews(kind TEXT PRIMARY KEY, record TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS practice_order_tests(id TEXT PRIMARY KEY, state TEXT NOT NULL, record TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS practice_order_test_events(id INTEGER PRIMARY KEY, test_id TEXT NOT NULL, at TEXT NOT NULL, state TEXT NOT NULL, record TEXT NOT NULL DEFAULT '{}');
            """)
            if "record" not in [row[1] for row in conn.execute("PRAGMA table_info(practice_order_test_events)")]:
                conn.execute("ALTER TABLE practice_order_test_events ADD COLUMN record TEXT NOT NULL DEFAULT '{}'")
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def read(self, identifier, review=False):
        if not self.path.exists():
            return None
        table, column = ("practice_test_reviews", "kind") if review else ("practice_order_tests", "id")
        with closing(sqlite3.connect(self.path.as_uri()+"?mode=ro", uri=True, timeout=2)) as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
                return None
            row = conn.execute(f"SELECT record FROM {table} WHERE {column}=?", (identifier,)).fetchone()
            return json.loads(row[0]) if row else None

    def review(self, kind, record):
        with self.transaction() as conn:
            conn.execute("INSERT OR REPLACE INTO practice_test_reviews VALUES (?,?)", (kind, json.dumps(record, allow_nan=False)))

    @staticmethod
    def save(conn, record):
        conn.execute("INSERT OR REPLACE INTO practice_order_tests VALUES (?,?,?)", (record["id"], record["state"], json.dumps(record, allow_nan=False)))
        conn.execute("INSERT INTO practice_order_test_events(test_id,at,state,record) VALUES(?,?,?,?)",
                     (record["id"], datetime.now(timezone.utc).isoformat(), record["state"],json.dumps(record,allow_nan=False)))

    def create(self, record):
        with self.transaction() as conn:
            if conn.execute("SELECT 1 FROM practice_order_tests WHERE id=?", (record["id"],)).fetchone():
                raise TestBlocked("Test identifier already exists")
            self.save(conn, record)

    def update(self, identifier, expected, **changes):
        with self.transaction() as conn:
            row = conn.execute("SELECT record FROM practice_order_tests WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise TestBlocked("Unknown Practice test identifier")
            record = json.loads(row[0])
            if record["state"] not in expected:
                raise TestBlocked("Test state changed or authorization already consumed; reconcile instead of retrying")
            record.update(changes)
            self.save(conn, record)
            return record
