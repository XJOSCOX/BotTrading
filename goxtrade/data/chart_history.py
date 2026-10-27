from datetime import datetime, timedelta, timezone
from contextlib import closing

import pandas as pd
from goxtrade.execution.contracts import contract_for_symbol
from goxtrade.execution.projectx_client import post

from goxtrade.data.live_store import attach_time, connect
from goxtrade.data.price_ticks import valid_price


def backfill_history(symbol, hours=48, reader=None):
    if type(hours) is not int or not 1<=hours<=24*16:
        raise ValueError("History lookback must be 1-384 hours")
    contract = contract_for_symbol(symbol)
    if not contract:
        raise ValueError("No contract mapping")
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start=end-timedelta(hours=hours)
    bars=[]
    cursor=start
    while cursor<end:
        chunk_end=min(end,cursor+timedelta(hours=48))
        payload=dict(contractId=contract,live=False,startTime=cursor.isoformat(),endTime=chunk_end.isoformat(),
                     unit=2,unitNumber=1,limit=3000,includePartialBar=False)
        if reader is None:
            response=post('/api/History/retrieveBars',payload)
            if response.get('success') is not True or not isinstance(response.get('bars'),list):
                raise RuntimeError('Historical data request failed')
            chunk=response['bars']
        else:
            chunk=reader.bars(payload)
        for bar in chunk:
            stamp=pd.Timestamp(bar['t'])
            if stamp.tzinfo is None or not pd.Timestamp(cursor)<=stamp<=pd.Timestamp(chunk_end):
                raise ValueError('Historical response includes an out-of-window candle')
        bars.extend(bar for bar in chunk if pd.Timestamp(bar['t'])<pd.Timestamp(chunk_end))
        cursor=chunk_end
    from goxtrade.strategies.vwap_ema_indicators import validate_minutes
    if any(b.get('contractId', contract) != contract for b in bars):
        raise ValueError('Historical response contract does not match the request')
    validated = validate_minutes(pd.DataFrame([dict(time=b['t'],open=b['o'],high=b['h'],low=b['l'],close=b['c'],volume=b.get('v'))
                                             for b in bars], columns=['time','open','high','low','close','volume']))
    validated = validated.loc[(validated['time']>=start)&(validated['time']+pd.Timedelta(minutes=1)<=end)]
    bars = [dict(t=row.time,o=row.open,h=row.high,l=row.low,c=row.close,v=row.volume) for row in validated.itertuples()]
    with closing(connect()) as conn:
        from goxtrade.data.strategy_history import initialize
        initialize(conn)
        retrieved = datetime.now(timezone.utc).isoformat()
        conn.executemany("INSERT OR REPLACE INTO strategy_historical_minutes (symbol,contract_id,time,open,high,low,close,volume,retrieved_at) VALUES (?,?,?,?,?,?,?,?,?)",
                         [(symbol, contract, pd.Timestamp(b['t']).tz_convert('UTC').isoformat(), b['o'], b['h'], b['l'], b['c'], b.get('v'), retrieved)
                          for b in bars if pd.Timestamp(b['t']) < end])
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
