"""Versioned research SQLite snapshots; large scans cannot lock the live-feed database."""
from contextlib import closing
from datetime import datetime, timezone
import json
import sqlite3
import uuid

import pandas as pd
from goxtrade.data import live_store
from goxtrade.execution.trade_candidate import digest, frozen_json
from goxtrade.data.historical_quality import quality, interval


def database_path():
    return live_store.DB_PATH.parent/"research_lab.db"


def connect():
    path=database_path()
    path.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(path,timeout=10)
    conn.row_factory=sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def progress_revision():
    path=database_path()
    if not path.exists():return None
    try:
        with closing(sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=.1)) as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='lab_jobs'").fetchone():return None
            return "|".join(str(v) for row in conn.execute("SELECT id,status,json_extract(record,'$.updated_at') FROM lab_jobs ORDER BY rowid DESC LIMIT 20") for v in row)
    except sqlite3.Error:
        return None  # Research storage failure must not break the trading display.


def schema(conn):
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='lab_schema'").fetchone():
        version=conn.execute("SELECT MAX(version) FROM lab_schema").fetchone()[0]
        if version!=1:
            raise ValueError("Unsupported research schema version; existing database preserved")
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS lab_schema(version INTEGER PRIMARY KEY);
    INSERT OR IGNORE INTO lab_schema VALUES(1);
    CREATE TABLE IF NOT EXISTS lab_datasets(id TEXT PRIMARY KEY,record TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS lab_bars(dataset TEXT NOT NULL,time TEXT NOT NULL,open REAL,high REAL,low REAL,close REAL,volume REAL,
      PRIMARY KEY(dataset,time));
    CREATE TABLE IF NOT EXISTS lab_jobs(id TEXT PRIMARY KEY,kind TEXT NOT NULL,status TEXT NOT NULL,record TEXT NOT NULL);
    CREATE UNIQUE INDEX IF NOT EXISTS lab_one_worker ON lab_jobs(status) WHERE status='running';
    CREATE TABLE IF NOT EXISTS lab_runs(id TEXT PRIMARY KEY,record TEXT NOT NULL);
    """)


def now():
    return datetime.now(timezone.utc).isoformat()


def read_rows(table, limit=100):
    if table not in ("lab_jobs","lab_datasets","lab_runs"):
        raise ValueError("Unsupported research table")
    with closing(connect()) as conn:
        schema(conn)
        return [json.loads(r[0]) for r in conn.execute(f"SELECT record FROM {table} ORDER BY rowid DESC LIMIT ?",(min(limit,200),))]


def get(table, identifier):
    if table not in ("lab_jobs","lab_datasets","lab_runs"):
        raise ValueError("Unsupported research table")
    with closing(connect()) as conn:
        schema(conn)
        row = conn.execute(f"SELECT record FROM {table} WHERE id=?",(identifier,)).fetchone()
    if not row:
        raise ValueError("Research item not found")
    return json.loads(row[0])


def frame(identifier, start=None, end=None, limit=300001):
    if not 1 <= limit <= 530000:
        raise ValueError("Bounded minute query required")
    meta = get("lab_datasets",identifier)
    start,end = interval(start or meta["start"],end or meta["end"])
    with closing(connect()) as conn:
        rows = conn.execute("SELECT time,open,high,low,close,volume FROM lab_bars WHERE dataset=? AND time>=? AND time<? ORDER BY time LIMIT ?",
                            (identifier,start.isoformat(),end.isoformat(),limit)).fetchall()
    result = pd.DataFrame([dict(r) for r in rows],columns=["time","open","high","low","close","volume"])
    result.attrs.update(contract_id=meta["contract_id"],provenance=meta["source"])
    return result


def save_dataset(frame, metadata):
    report = quality(frame, metadata)
    if report["status"] in ("invalid","unsupported"):
        raise ValueError("Dataset rejected: "+"; ".join(report["errors"]))
    normalized = frame[["time","open","high","low","close","volume"]].copy()
    normalized["time"] = pd.to_datetime(normalized["time"],utc=True).map(lambda t:t.isoformat())
    from goxtrade.research.datasets import dataset_hash
    content_hash = dataset_hash(normalized)
    identifier = digest(dict(hash=content_hash,metadata=metadata))
    record = dict(**metadata,id=identifier,content_hash=content_hash,quality=report,retrieved_at=now(),schema_version=1)
    with closing(connect()) as conn:
        schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        try:
            if not conn.execute("SELECT 1 FROM lab_datasets WHERE id=?",(identifier,)).fetchone():
                conn.executemany("INSERT INTO lab_bars VALUES(?,?,?,?,?,?,?)",[(identifier,row.time,row.open,row.high,row.low,row.close,row.volume) for row in normalized.itertuples(index=False)])
                conn.execute("INSERT INTO lab_datasets VALUES(?,?)",(identifier,frozen_json(record)))
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    return get("lab_datasets",identifier)


def job(kind, request):
    identifier = digest(dict(kind=kind,request=request))
    record = dict(id=identifier,kind=kind,status="queued",request=request,created_at=now(),updated_at=now(),progress=0,cursor=request.get("start"),events=[],cancel=False)
    with closing(connect()) as conn:
        schema(conn)
        conn.execute("INSERT OR IGNORE INTO lab_jobs VALUES(?,?,?,?)",(identifier,kind,"queued",frozen_json(record)))
        conn.commit()
    return get("lab_jobs",identifier)


def update_job(identifier, expected_owner=None, **changes):
    with closing(connect()) as conn:
        schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT record FROM lab_jobs WHERE id=?",(identifier,)).fetchone()
        if not row:
            raise ValueError("Unknown job")
        record = json.loads(row[0])
        if expected_owner is not None and record.get("owner") != expected_owner:
            raise ValueError("Research lease changed; stale worker cannot commit")
        record.update(changes,updated_at=now())
        conn.execute("UPDATE lab_jobs SET status=?,record=? WHERE id=?",(record["status"],frozen_json(record),identifier))
        conn.commit()
    return record


def claim(identifier):
    with closing(connect()) as conn:
        schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT record FROM lab_jobs WHERE id=?",(identifier,)).fetchone()
        if not row:
            raise ValueError("Unknown job")
        record = json.loads(row[0])
        # Explicit resume only; no startup auto-runs or concurrent takeover.
        if record["status"] == "running":
            if (pd.Timestamp(now())-pd.Timestamp(record["updated_at"])).total_seconds() < 600:
                raise ValueError("Research job already running")
        elif record["status"] == "complete":
            conn.rollback()
            return None
        record.update(status="running",cancel=False,updated_at=now(),owner=uuid.uuid4().hex)
        try:
            conn.execute("UPDATE lab_jobs SET status='running',record=? WHERE id=?",(frozen_json(record),identifier))
            conn.commit()
        except sqlite3.IntegrityError as error:
            conn.rollback()
            raise ValueError("Another research job is running; resume after it finishes") from error
    return record


def stage_chunk(identifier, rows, cursor, event, owner=None):
    """Data and cursor commit together, so retry cannot skip an uncommitted chunk."""
    with closing(connect()) as conn:
        schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        job = json.loads(conn.execute("SELECT record FROM lab_jobs WHERE id=?",(identifier,)).fetchone()[0])
        if owner is not None and job.get("owner") != owner:
            raise ValueError("Research lease changed; stale chunk cannot commit")
        if job["cancel"]:
            conn.rollback()
            return False
        for row in rows:
            values = tuple(row[k] for k in ("time","open","high","low","close","volume"))
            previous = conn.execute("SELECT time,open,high,low,close,volume FROM lab_bars WHERE dataset=? AND time=?",(identifier,row["time"])).fetchone()
            if previous and tuple(previous) != values:
                raise ValueError("Conflicting provider revision; existing chunk preserved")
            conn.execute("INSERT OR IGNORE INTO lab_bars VALUES(?,?,?,?,?,?,?)",(identifier,*values))
        job.update(cursor=cursor,updated_at=now(),events=(job["events"]+[event])[-400:])
        start,end = interval(job["request"]["start"],job["request"]["end"])
        job["progress"] = min(1.,(pd.Timestamp(cursor)-start)/(end-start))
        conn.execute("UPDATE lab_jobs SET record=? WHERE id=?",(frozen_json(job),identifier))
        conn.commit()
    return True


def staged_frame(identifier):
    with closing(connect()) as conn:
        return pd.DataFrame([dict(r) for r in conn.execute("SELECT time,open,high,low,close,volume FROM lab_bars WHERE dataset=? ORDER BY time",(identifier,))],columns=["time","open","high","low","close","volume"])


def save_run(record):
    with closing(connect()) as conn:
        schema(conn)
        conn.execute("INSERT OR IGNORE INTO lab_runs VALUES(?,?)",(record["id"],frozen_json(record)))
        conn.commit()


def verify_dataset(identifier):
    """Recompute canonical content integrity using bounded SQL batches."""
    import hashlib
    meta=get("lab_datasets",identifier)
    checksum=hashlib.sha256()
    columns=["time","open","high","low","close","volume"]
    header=True
    with closing(connect()) as conn:
        cursor=conn.execute("SELECT time,open,high,low,close,volume FROM lab_bars WHERE dataset=? ORDER BY time",(identifier,))
        while True:
            rows=cursor.fetchmany(2000)
            if not rows:break
            checksum.update(pd.DataFrame([tuple(r) for r in rows],columns=columns).to_csv(index=False,header=header,float_format="%.12g").encode())
            header=False
    if header:
        checksum.update(pd.DataFrame(columns=columns).to_csv(index=False).encode())
    if checksum.hexdigest()!=meta["content_hash"]:
        raise ValueError("Research dataset integrity mismatch; original content cannot be reproduced")
    return True


def run_summaries():
    with closing(connect()) as conn:
        schema(conn)
        rows=conn.execute("SELECT id,json_extract(record,'$.created_at'),json_extract(record,'$.result.summary.metrics'),json_extract(record,'$.code') FROM lab_runs ORDER BY rowid DESC LIMIT 30").fetchall()
    return [dict(id=r[0],created_at=r[1],metrics=json.loads(r[2]),code=json.loads(r[3])) for r in rows]
