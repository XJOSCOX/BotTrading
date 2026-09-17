from datetime import datetime, timedelta, timezone
from contextlib import closing

import pandas as pd
from contracts import contract_for_symbol
from projectx_client import post

from live_store import attach_time, connect
from price_ticks import valid_price


def backfill_history(symbol):
    contract = contract_for_symbol(symbol)
    if not contract:
        raise ValueError("No contract mapping")
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    response = post('/api/History/retrieveBars', {
        'contractId': contract, 'live': False, 'startTime': (end - timedelta(hours=48)).isoformat(),
        'endTime': end.isoformat(), 'unit': 2, 'unitNumber': 1, 'limit': 3000, 'includePartialBar': False,
    })
    if not response.get('success'):
        raise RuntimeError('Historical data request failed')
    bars = response.get('bars') or []
    with closing(connect()) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS historical_minutes (symbol TEXT,time TEXT,open REAL,high REAL,low REAL,close REAL,PRIMARY KEY(symbol,time))')
        if 'volume' not in [r[1] for r in conn.execute('PRAGMA table_info(historical_minutes)')]:
            conn.execute('ALTER TABLE historical_minutes ADD COLUMN volume REAL')
        conn.executemany('INSERT OR REPLACE INTO historical_minutes (symbol,time,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?)',
                         [(symbol, pd.Timestamp(b['t']).tz_convert('UTC').strftime('%Y-%m-%dT%H:%M:00+00:00'), b['o'], b['h'], b['l'], b['c'], b.get('v'))
                          for b in bars if pd.Timestamp(b['t']) < end])
        conn.commit()
    return len(bars)


def chart_history(symbol, hours=48):
    """Persist minute candles incrementally without limiting history by tick count."""
    with closing(connect()) as conn:
        conn.execute("CREATE INDEX IF NOT EXISTS ticks_symbol_id ON live_ticks(symbol, id)")
        conn.execute("CREATE TABLE IF NOT EXISTS chart_minutes (symbol TEXT, time TEXT, open REAL, high REAL, low REAL, close REAL, PRIMARY KEY(symbol,time))")
        conn.execute("CREATE TABLE IF NOT EXISTS chart_cursor (symbol TEXT PRIMARY KEY, tick_id INTEGER)")
        if 'volume' not in [r[1] for r in conn.execute('PRAGMA table_info(chart_minutes)')]:
            conn.execute('ALTER TABLE chart_minutes ADD COLUMN volume REAL DEFAULT 0')
            # Replay stored trades once to populate volume for existing candles.
            conn.execute('DELETE FROM chart_cursor')
            conn.commit()
        conn.execute("CREATE TABLE IF NOT EXISTS chart_tick_version (symbol TEXT PRIMARY KEY)")
        if not conn.execute("SELECT 1 FROM chart_tick_version WHERE symbol=?", (symbol,)).fetchone():
            # Only derived candles are rebuilt; raw ticks and alert history stay intact.
            conn.execute("DELETE FROM chart_minutes WHERE symbol=?", (symbol,))
            conn.execute("DELETE FROM chart_cursor WHERE symbol=?", (symbol,))
            conn.execute("INSERT INTO chart_tick_version VALUES (?)", (symbol,))
        conn.commit()
        # A fixed snapshot allows the initial catch-up to finish while ticks arrive.
        end = conn.execute("SELECT COALESCE(MAX(id),0) FROM live_ticks WHERE symbol=?", (symbol,)).fetchone()[0]
        while True:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT tick_id FROM chart_cursor WHERE symbol=?", (symbol,)).fetchone()
            cursor = row[0] if row else 0
            rows = conn.execute("SELECT id,event_time,received_at,price,event_type,volume FROM live_ticks WHERE symbol=? AND id>? AND id<=? ORDER BY id LIMIT 20000", (symbol, cursor, end)).fetchall()
            if not rows:
                conn.commit()
                break
            frame = attach_time(pd.DataFrame([dict(r) for r in rows])).dropna(subset=['price','time'])
            if not frame.empty:
                frame["price"] = frame["price"].map(lambda value: valid_price(symbol, value))
                frame = frame.dropna(subset=["price"])
            if not frame.empty:
                frame['minute'] = frame['time'].dt.floor('min').dt.strftime('%Y-%m-%dT%H:%M:00+00:00')
                bars = frame.groupby('minute')['price'].agg(['first','max','min','last'])
                frame['trade_volume'] = pd.to_numeric(frame['volume'], errors='coerce').fillna(0).where(frame['event_type'].eq('trade'), 0)
                bars['volume'] = frame.groupby('minute')['trade_volume'].sum()
                conn.executemany("""INSERT INTO chart_minutes (symbol,time,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(symbol,time) DO UPDATE SET high=MAX(high,excluded.high),
                    low=MIN(low,excluded.low), close=excluded.close, volume=chart_minutes.volume+excluded.volume""",
                    [(symbol, minute, *values) for minute, values in zip(bars.index, bars.itertuples(index=False, name=None))])
            conn.execute("INSERT OR REPLACE INTO chart_cursor VALUES (?,?)", (symbol, rows[-1]['id']))
            conn.commit()
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:00+00:00')
        rows = conn.execute("SELECT time,open,high,low,close,volume FROM chart_minutes WHERE symbol=? AND time>=? ORDER BY time", (symbol, cutoff)).fetchall()
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='historical_minutes'").fetchone():
            if 'volume' not in [r[1] for r in conn.execute('PRAGMA table_info(historical_minutes)')]:
                conn.execute('ALTER TABLE historical_minutes ADD COLUMN volume REAL')
            rows += conn.execute("SELECT time,open,high,low,close,volume FROM historical_minutes WHERE symbol=? AND time>=? ORDER BY time", (symbol, cutoff)).fetchall()
    result = pd.DataFrame([dict(r) for r in rows], columns=['time','open','high','low','close','volume'])
    result['time'] = pd.to_datetime(result['time'], utc=True)
    return result.drop_duplicates('time', keep='last').sort_values('time').reset_index(drop=True)
