"""Contract-specific OHLCV from trade events, separate from display chart candles."""
from contextlib import closing
import math

import pandas as pd

from goxtrade.data.live_store import connect
from goxtrade.data.price_ticks import valid_price


def initialize(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS strategy_trade_cursor (symbol TEXT,contract_id TEXT,tick_id INTEGER,PRIMARY KEY(symbol,contract_id))")
    conn.execute("""CREATE TABLE IF NOT EXISTS strategy_trade_minutes (
        symbol TEXT,contract_id TEXT,time TEXT,open REAL,high REAL,low REAL,close REAL,
        volume REAL,first_event TEXT,last_event TEXT,asof_time TEXT,last_sequence INTEGER,
        invalid_volume INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(symbol,contract_id,time))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS strategy_historical_minutes (
        symbol TEXT,contract_id TEXT,time TEXT,open REAL,high REAL,low REAL,close REAL,volume REAL,
        PRIMARY KEY(symbol,contract_id,time))""")
    if "retrieved_at" not in {row[1] for row in conn.execute("PRAGMA table_info(strategy_historical_minutes)")}:
        conn.execute("ALTER TABLE strategy_historical_minutes ADD COLUMN retrieved_at TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS strategy_ticks_contract ON live_ticks(symbol,contract_id,id)")
    conn.commit()


def refresh_trade_minutes(symbol, contract_id):
    with closing(connect()) as conn:
        initialize(conn)
        end = conn.execute("SELECT COALESCE(MAX(id),0) FROM live_ticks WHERE symbol=? AND contract_id=?", (symbol, contract_id)).fetchone()[0]
        while True:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT tick_id FROM strategy_trade_cursor WHERE symbol=? AND contract_id=?", (symbol, contract_id)).fetchone()
            cursor = row[0] if row else 0
            rows = conn.execute("SELECT id,price,volume,event_time,received_at FROM live_ticks WHERE symbol=? AND contract_id=? AND event_type='trade' AND id>? AND id<=? ORDER BY id LIMIT 20000",
                                (symbol, contract_id, cursor, end)).fetchall()
            if not rows:
                conn.execute("INSERT OR REPLACE INTO strategy_trade_cursor VALUES (?,?,?)", (symbol, contract_id, end))
                conn.commit()
                break
            buckets = {}
            for row in rows:
                price = valid_price(symbol, row["price"])
                stamp = pd.to_datetime(row["event_time"], utc=True, errors="coerce")
                observed = pd.to_datetime(row["received_at"], utc=True, errors="coerce")
                if price is None or pd.isna(stamp) or pd.isna(observed):
                    continue
                minute = stamp.floor("min").isoformat()
                event = stamp.isoformat()
                item = buckets.setdefault(minute, dict(open=price, high=price, low=price, close=price,
                                                       first=event, last=event, asof=observed.isoformat(),
                                                       sequence=row["id"], volume=0., invalid=0))
                item["high"], item["low"] = max(item["high"], price), min(item["low"], price)
                if event < item["first"]:
                    item.update(open=price, first=event)
                if event >= item["last"]:
                    item.update(close=price, last=event)
                item["asof"] = max(item["asof"], observed.isoformat())
                item["sequence"] = max(item["sequence"], row["id"])
                volume = row["volume"]
                if not isinstance(volume, (float, int)) or not math.isfinite(volume) or volume < 0:
                    item["invalid"] = 1
                else:
                    item["volume"] += volume
            conn.executemany("""INSERT INTO strategy_trade_minutes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(symbol,contract_id,time) DO UPDATE SET
                open=CASE WHEN excluded.first_event<first_event THEN excluded.open ELSE open END,
                high=MAX(high,excluded.high),low=MIN(low,excluded.low),
                close=CASE WHEN excluded.last_event>=last_event THEN excluded.close ELSE close END,
                volume=volume+excluded.volume,first_event=MIN(first_event,excluded.first_event),
                last_event=MAX(last_event,excluded.last_event),asof_time=MAX(asof_time,excluded.asof_time),
                last_sequence=MAX(last_sequence,excluded.last_sequence),invalid_volume=MAX(invalid_volume,excluded.invalid_volume)""",
                [(symbol, contract_id, stamp, item["open"], item["high"], item["low"], item["close"], item["volume"],
                  item["first"], item["last"], item["asof"], item["sequence"], item["invalid"]) for stamp, item in buckets.items()])
            conn.execute("INSERT OR REPLACE INTO strategy_trade_cursor VALUES (?,?,?)", (symbol, contract_id, rows[-1]["id"]))
            conn.commit()


def load_strategy_minutes(symbol, contract_id, now, hours=72, refresh=True):
    now = pd.Timestamp(now).tz_convert("UTC")
    if refresh:
        refresh_trade_minutes(symbol, contract_id)
    cutoff = (now-pd.Timedelta(hours=hours)).floor("min").isoformat()
    with closing(connect()) as conn:
        initialize(conn)
        trades = [dict(row) for row in conn.execute("SELECT time,open,high,low,close,volume,asof_time,last_sequence,invalid_volume FROM strategy_trade_minutes WHERE symbol=? AND contract_id=? AND time>=? ORDER BY time", (symbol, contract_id, cutoff))]
        saved = [dict(row) for row in conn.execute("SELECT time,open,high,low,close,volume,retrieved_at FROM strategy_historical_minutes WHERE symbol=? AND contract_id=? AND time>=? ORDER BY time", (symbol, contract_id, cutoff))]
        from goxtrade.data.feed_coverage import windows
        coverage = windows(conn, symbol, contract_id)
    by_time = {}
    for row in trades:
        if row.pop("invalid_volume"):
            row["volume"] = float("nan")
        if pd.Timestamp(row["asof_time"]) <= now:
            stamp = pd.Timestamp(row["time"])
            row["complete"] = stamp+pd.Timedelta(minutes=1) <= now and any(
                stamp >= start.ceil("min") and stamp+pd.Timedelta(minutes=1) <= (end if end is not None else now)
                for start, end in coverage)
            by_time[pd.Timestamp(row["time"])] = row
    for row in saved:
        stamp = pd.Timestamp(row["time"])
        observed = pd.Timestamp(row.pop("retrieved_at") or now)
        if stamp+pd.Timedelta(minutes=1) <= now and observed <= now:
            # A full historical bar replaces a partial local capture; volumes are never added together.
            by_time[stamp] = {**row, "last_sequence": 0, "asof_time": observed.isoformat(), "complete": True}
    frame = pd.DataFrame(by_time.values(), columns=["time", "open", "high", "low", "close", "volume", "asof_time", "last_sequence", "complete"])
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    frame = frame.loc[frame["time"] <= now.floor("min")].sort_values("time").reset_index(drop=True)
    frame.attrs.update(contract_id=contract_id, provenance="contract-specific saved broker bars / sequenced trades")
    frame.attrs["coverage_limitation"] = "Connection windows cannot establish exchange-level exactly-once delivery; backfilled bars are authoritative."
    return frame


def latest_trade(symbol, contract_id, as_of=None):
    with closing(connect()) as conn:
        rows = conn.execute("SELECT id,price,event_time,received_at FROM live_ticks WHERE symbol=? AND contract_id=? AND event_type='trade' AND price IS NOT NULL ORDER BY id DESC LIMIT 100", (symbol, contract_id)).fetchall()
    for row in rows:
        if as_of is None or all(pd.Timestamp(row[field])<=pd.Timestamp(as_of) for field in ('event_time','received_at')):
            return dict(row)
    return None
