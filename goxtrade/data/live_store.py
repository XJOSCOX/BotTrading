from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pandas as pd
from goxtrade.data.price_ticks import valid_price, price_predicate


from goxtrade.paths import DATA_DIR
DB_PATH = DATA_DIR / "live_market.db"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    # Existing readers must not compete for a schema write lock with the tick writer.
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('live_ticks','latest_quotes')")}
    if tables != {"live_ticks", "latest_quotes"}:
        init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        create table if not exists live_ticks (
            id integer primary key autoincrement,
            symbol text not null,
            contract_id text not null,
            event_type text not null,
            price real,
            best_bid real,
            best_ask real,
            volume real,
            event_time text,
            received_at text not null
        )
        """
    )
    conn.execute(
        """
        create table if not exists latest_quotes (
            symbol text primary key,
            contract_id text not null,
            last_price real,
            best_bid real,
            best_ask real,
            volume real,
            event_time text,
            received_at text not null
        )
        """
    )
    conn.commit()


def save_quote(symbol: str, contract_id: str, payload: dict) -> None:
    price = valid_price(symbol, payload.get("lastPrice"))
    best_bid = payload.get("bestBid")
    best_ask = payload.get("bestAsk")
    volume = payload.get("volume")
    event_time = payload.get("timestamp") or payload.get("lastUpdated")
    received_at = utc_now()
    with closing(connect()) as conn:
        conn.execute(
            """
            insert into live_ticks
            (symbol, contract_id, event_type, price, best_bid, best_ask, volume, event_time, received_at)
            values (?, ?, 'quote', ?, ?, ?, ?, ?, ?)
            """,
            (symbol, contract_id, price, best_bid, best_ask, volume, event_time, received_at),
        )
        update_quote(conn, symbol, contract_id, payload, received_at)
        conn.commit()


def update_quote(conn, symbol, contract_id, payload, received_at):
    """Merge omitted fields, never explicit nulls or timestamps from old sides."""
    previous = conn.execute("SELECT * FROM latest_quotes WHERE symbol=?", (symbol,)).fetchone()
    previous = dict(previous) if previous and previous["contract_id"] == contract_id else {}
    stamp = payload.get("timestamp") or payload.get("lastUpdated")

    def parsed(value):
        try:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return result if result.tzinfo is not None else None
        except (ValueError, TypeError):
            return None

    old_time, new_time = parsed(previous.get("event_time")), parsed(stamp)
    if old_time is not None and new_time is not None and new_time < old_time:
        return  # Raw events are retained, but delayed quotes cannot regress the cache.
    fields = {column: payload[key] if key in payload else previous.get(column)
              for key, column in (("lastPrice", "last_price"), ("bestBid", "best_bid"),
                                  ("bestAsk", "best_ask"), ("volume", "volume"))}
    fields["last_price"] = valid_price(symbol, fields["last_price"])
    if previous and ("bestBid" not in payload or "bestAsk" not in payload):
        # A partial update must not renew the freshness of the carried quote side.
        stamp = min(old_time, new_time).isoformat() if old_time and new_time else None
        old_received, new_received = parsed(previous.get("received_at")), parsed(received_at)
        received_at = min(old_received, new_received).isoformat() if old_received and new_received else received_at
    conn.execute("""INSERT INTO latest_quotes
        (symbol,contract_id,last_price,best_bid,best_ask,volume,event_time,received_at)
        VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET
        contract_id=excluded.contract_id,last_price=excluded.last_price,
        best_bid=excluded.best_bid,best_ask=excluded.best_ask,volume=excluded.volume,
        event_time=excluded.event_time,received_at=excluded.received_at""",
        (symbol, contract_id, fields["last_price"], fields["best_bid"], fields["best_ask"],
         fields["volume"], stamp, received_at))


def save_trade(symbol: str, contract_id: str, payload: dict) -> None:
    received_at = utc_now()
    with closing(connect()) as conn:
        conn.execute(
            """
            insert into live_ticks
            (symbol, contract_id, event_type, price, volume, event_time, received_at)
            values (?, ?, 'trade', ?, ?, ?, ?)
            """,
            (symbol, contract_id, valid_price(symbol, payload.get("price")), payload.get("volume"), payload.get("timestamp"), received_at),
        )
        conn.commit()


def latest_quotes() -> pd.DataFrame:
    with closing(connect()) as conn:
        rows = conn.execute("select * from latest_quotes order by symbol").fetchall()
    return pd.DataFrame([dict(row) for row in rows])


def latest_prices(symbols) -> dict:
    """Read the latest priced feed event without loading candle history."""
    with closing(connect()) as conn:
        result = {}
        for symbol in symbols:
            row = conn.execute(
                "SELECT id, price, event_time, received_at FROM live_ticks "
                f"WHERE symbol=? AND {price_predicate(symbol)} ORDER BY id DESC LIMIT 1",
                (symbol,),
            ).fetchone()
            if row:
                result[symbol] = dict(row)
        return result


def reported_session_volume(symbol: str):
    """Quote volume is cumulative; never sum it across repeated updates."""
    conn = connect()
    try:
        row = conn.execute(
            "SELECT volume FROM live_ticks WHERE symbol=? AND event_type='quote' AND volume IS NOT NULL ORDER BY id DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        return row['volume'] if row else None
    finally:
        conn.close()


def attach_time(data: pd.DataFrame) -> pd.DataFrame:
    parsed_event_time = pd.to_datetime(data["event_time"], format="mixed", errors="coerce", utc=True)
    parsed_received_at = pd.to_datetime(data["received_at"], format="mixed", errors="coerce", utc=True)
    data["time"] = parsed_event_time.fillna(parsed_received_at)
    return data


def ticks_for_symbol(symbol: str, limit: int = 500) -> pd.DataFrame:
    with closing(connect()) as conn:
        rows = conn.execute(
            f"""
            select * from live_ticks
            where symbol = ? and {price_predicate(symbol)}
            order by id desc
            limit ?
            """,
            (symbol, limit),
        ).fetchall()
    data = pd.DataFrame([dict(row) for row in rows])
    if data.empty:
        return data
    return attach_time(data).sort_values("id")


def price_history_for_symbol(symbol: str, hours: int = 24, max_rows: int = 50000) -> pd.DataFrame:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="milliseconds")
    with closing(connect()) as conn:
        rows = conn.execute(
            f"""
            select * from live_ticks
            where symbol = ?
              and {price_predicate(symbol)}
              and received_at >= ?
            order by id desc
            limit ?
            """,
            (symbol, cutoff, max_rows),
        ).fetchall()
    data = pd.DataFrame([dict(row) for row in rows])
    if data.empty:
        return data
    return attach_time(data).sort_values("id")
