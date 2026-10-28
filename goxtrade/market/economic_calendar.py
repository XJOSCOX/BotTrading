"""Persisted scheduled-news entry overlay. Never closes or manages positions."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
import json
import re
import sqlite3
import threading
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
from goxtrade.data.live_store import connect
from goxtrade.config.execution_identity import PROFILE

SOURCES = {"fed": "https://www.federalreserve.gov/json/calendar.json",
           "bea": "https://www.bea.gov/news/schedule"}
DEFAULTS = dict(enabled=False, before_minutes=15, after_minutes=30,
                critical_before_minutes=30, critical_after_minutes=60,
                impacts=["critical", "high"], stale_hours=72)
_refresh_lock = threading.Lock()


def utc(value):
    value = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value,str) else value
    if not isinstance(value,datetime) or value.tzinfo is None:
        raise ValueError("Event time must include a timezone offset")
    return value.astimezone(timezone.utc)


def init(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS economic_calendar_settings (id INTEGER PRIMARY KEY, record TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS economic_events (id TEXT PRIMARY KEY, source TEXT NOT NULL, event_at TEXT NOT NULL, record TEXT NOT NULL)")
    conn.execute("CREATE INDEX IF NOT EXISTS economic_event_time ON economic_events(event_at)")
    conn.execute("CREATE TABLE IF NOT EXISTS economic_calendar_sources (id TEXT PRIMARY KEY, record TEXT NOT NULL)")


def exists(conn, table):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone() is not None


def settings():
    with closing(connect()) as conn:
        row = conn.execute("SELECT record FROM economic_calendar_settings WHERE id=1").fetchone() if exists(conn,"economic_calendar_settings") else None
    return {**DEFAULTS, **(json.loads(row[0]) if row else {})}


def save_settings(values):
    if set(values) != set(DEFAULTS) or type(values['enabled']) is not bool:
        raise ValueError("Invalid economic calendar settings")
    for key in ('before_minutes','after_minutes','critical_before_minutes','critical_after_minutes'):
        if type(values[key]) is not int or not 0 <= values[key] <= 240:
            raise ValueError("Event buffers must be 0-240 minutes")
    if type(values['stale_hours']) is not int or not 1 <= values['stale_hours'] <= 168:
        raise ValueError("Calendar freshness must be 1-168 hours")
    if not isinstance(values['impacts'],list) or not set(values['impacts']) <= {'critical','high','medium','low'}:
        raise ValueError("Invalid event impact selection")
    with closing(connect()) as conn:
        init(conn)
        conn.execute("INSERT OR REPLACE INTO economic_calendar_settings VALUES(1,?)",(json.dumps(values),))
        conn.commit()


def event(title, at, impact, source_url, source="manual", *, now=None, identifier=None):
    at = utc(at)
    parsed = urlparse(source_url)
    if not isinstance(title,str) or not 1 <= len(title.strip()) <= 200 or parsed.scheme != 'https' or not parsed.hostname or parsed.username:
        raise ValueError("Provide an event title and an HTTPS reference")
    if impact not in ('critical','high','medium','low'):
        raise ValueError("Invalid event impact")
    key = identifier or sha256(f'{source}|{title.strip()}|{at.isoformat()}'.encode()).hexdigest()
    return dict(id=key, title=unescape(title.strip()), event_at=at.isoformat(), impact=impact,
                source=source, source_url=source_url, reviewed_at=utc(now or datetime.now(timezone.utc)).isoformat())


def add_event(values):
    row = event(values['title'],values['event_at'],values['impact'],values['source_url'])
    with closing(connect()) as conn:
        init(conn)
        conn.execute("INSERT OR REPLACE INTO economic_events VALUES(?,?,?,?)",(row['id'],row['source'],row['event_at'],json.dumps(row)))
        conn.commit()
    return row


def delete_event(identifier):
    with closing(connect()) as conn:
        init(conn)
        conn.execute("DELETE FROM economic_events WHERE id=? AND source='manual'",(identifier,))
        conn.commit()


def fed_events(payload, now):
    rows=[]
    for item in payload['events']:
        if not re.fullmatch(r'\d{4}-\d{2}',str(item.get('month',''))):
            continue
        # Exclude approximate/all-day dates: never invent release times.
        clock=str(item.get('time','')).lower().replace('.','').strip()
        days=str(item.get('days','')).strip()
        if not re.fullmatch(r'\d{1,2}:\d{2} [ap]m',clock) or not re.fullmatch(r'\d{1,2}(?:,\s*\d{1,2})*',days):
            continue
        title=item.get('title','').strip()
        impact='critical' if item.get('type')=='FOMC' and 'Minutes' not in title else 'high' if item.get('type')=='FOMC' else 'medium' if item.get('type')=='Speeches' else 'low'
        for day in days.split(','):
            at=datetime.strptime(f"{item['month']}-{int(day):02} {clock}",'%Y-%m-%d %I:%M %p').replace(tzinfo=ZoneInfo('America/New_York'))
            if now-timedelta(days=7) <= at <= now+timedelta(days=180):
                rows.append(event(title,at,impact,SOURCES['fed'],'fed',now=now))
    return rows


class BeaTable(HTMLParser):
    def __init__(self):
        super().__init__(); self.active=False; self.cell=None; self.parts=[]; self.rows=[]; self.row=[]; self.year=None

    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=='table' and attrs.get('id')=='release-schedule-table': self.active=True
        if self.active and tag=='tr': self.row=[]
        if self.active and tag in ('td','th'): self.cell=tag; self.parts=[]

    def handle_data(self,data):
        if self.active and self.cell: self.parts.append(data)

    def handle_endtag(self,tag):
        if self.active and tag in ('td','th') and self.cell:
            text=' '.join(' '.join(self.parts).split())
            if tag=='th' and re.fullmatch(r'Year \d{4}',text): self.year=int(text[-4:])
            self.row.append(text); self.cell=None
        if self.active and tag=='tr' and len(self.row)==3: self.rows.append(self.row)
        if tag=='table': self.active=False


def bea_events(html,now):
    table=BeaTable(); table.feed(html)
    if table.year is None: raise ValueError('BEA calendar year unavailable')
    rows=[]
    for when,kind,title in table.rows:
        if not re.fullmatch(r'[A-Za-z]+ \d{1,2} \d{1,2}:\d{2} [AP]M',when): continue
        at=datetime.strptime(f'{table.year} {when}','%Y %B %d %I:%M %p').replace(tzinfo=ZoneInfo('America/New_York'))
        if now-timedelta(days=7) <= at <= now+timedelta(days=180):
            impact='high' if title.startswith(('GDP','Personal Income and Outlays')) else 'medium'
            rows.append(event(title,at,impact,SOURCES['bea'],'bea',now=now))
    return rows


def refresh(now=None):
    now=utc(now or datetime.now(timezone.utc))
    if not _refresh_lock.acquire(blocking=False): return dict(message='Calendar refresh already running')
    try:
        for source,url in SOURCES.items():
            try:
                response=requests.get(url,timeout=(5,20),allow_redirects=False)
                response.raise_for_status()
                if len(response.content)>2_000_000: raise ValueError('Calendar response too large')
                rows=fed_events(json.loads(response.content.decode('utf-8-sig')),now) if source=='fed' else bea_events(response.text,now)
                if not rows or not any(utc(r['event_at'])>=now for r in rows): raise ValueError('No upcoming dated events found')
                with closing(connect()) as conn:
                    init(conn)
                    conn.execute('DELETE FROM economic_events WHERE source=?',(source,))
                    conn.executemany('INSERT INTO economic_events VALUES(?,?,?,?)',[(r['id'],source,r['event_at'],json.dumps(r)) for r in rows])
                    conn.execute('INSERT OR REPLACE INTO economic_calendar_sources VALUES(?,?)',(source,json.dumps(dict(updated_at=now.isoformat(),attempted_at=now.isoformat(),error=None,count=len(rows),url=url))))
                    conn.commit()
            except (requests.RequestException,ValueError,KeyError,TypeError) as error:
                with closing(connect()) as conn:
                    init(conn)
                    old=conn.execute('SELECT record FROM economic_calendar_sources WHERE id=?',(source,)).fetchone()
                    state=json.loads(old[0]) if old else dict(url=url)
                    state.update(attempted_at=now.isoformat(),error=f'{type(error).__name__}: calendar refresh failed; previous events retained')
                    conn.execute('INSERT OR REPLACE INTO economic_calendar_sources VALUES(?,?)',(source,json.dumps(state))); conn.commit()
        return snapshot(now)
    finally:
        _refresh_lock.release()


def entry_block(now,profile=None):
    if (profile or PROFILE) != 'practice': return None
    try:
        return _entry_block(now)
    except (OSError,sqlite3.DatabaseError,ValueError,TypeError,KeyError):
        return 'Economic calendar unavailable; new entries paused, existing exits unchanged'


def _entry_block(now):
    now=utc(now); policy=settings()
    if not policy['enabled']: return None
    with closing(connect()) as conn:
        if not exists(conn,'economic_calendar_sources'): return 'Economic calendar: source coverage unavailable; new entries paused'
        sources={r[0]:json.loads(r[1]) for r in conn.execute('SELECT id,record FROM economic_calendar_sources')}
        for source in SOURCES:
            stamp=sources.get(source,{}).get('updated_at')
            if not stamp or not 0 <= (now-utc(stamp)).total_seconds() <= policy['stale_hours']*3600:
                return f'Economic calendar: {source.upper()} schedule missing or stale; refresh required'
        if not exists(conn,'economic_events'): return 'Economic calendar: events unavailable; new entries paused'
        margin=timedelta(minutes=240)
        rows=conn.execute('SELECT record FROM economic_events WHERE event_at>=? AND event_at<=?',((now-margin).isoformat(),(now+margin).isoformat()))
        active=[]
        for raw, in rows:
            row=json.loads(raw)
            if row['impact'] not in policy['impacts']: continue
            prefix='critical_' if row['impact']=='critical' else ''
            begin=utc(row['event_at'])-timedelta(minutes=policy[prefix+'before_minutes'])
            end=utc(row['event_at'])+timedelta(minutes=policy[prefix+'after_minutes'])
            if begin <= now < end: active.append((end,row))
        if active:
            end,row=max(active,key=lambda item:item[0])
            local=end.astimezone(ZoneInfo('America/Chicago'))
            return f"Economic event: {row['title']}; new entries paused until {local:%b %d %H:%M} CT"
    return None


def chicago_time(value):
    parsed=datetime.fromisoformat(value)
    if parsed.tzinfo is not None: return utc(parsed)
    zone=ZoneInfo('America/Chicago')
    first,second=(parsed.replace(tzinfo=zone,fold=fold) for fold in (0,1))
    if first.utcoffset()!=second.utcoffset() or first.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)!=parsed:
        raise ValueError('Ambiguous or nonexistent Chicago time; provide an explicit UTC offset')
    return utc(first)


def snapshot(now=None):
    now=utc(now or datetime.now(timezone.utc))
    with closing(connect()) as conn:
        rows=conn.execute('SELECT record FROM economic_events WHERE event_at>=? ORDER BY event_at',((now-timedelta(days=7)).isoformat(),)).fetchall() if exists(conn,'economic_events') else []
        sources={r[0]:json.loads(r[1]) for r in conn.execute('SELECT id,record FROM economic_calendar_sources')} if exists(conn,'economic_calendar_sources') else {}
        worker=conn.execute('SELECT status FROM practice_control WHERE id=1').fetchone() if exists(conn,'practice_control') else None
    from goxtrade.runtime.build_identity import fingerprint
    runtime=json.loads(worker[0]) if worker else {}
    runtime_ready=(runtime.get('worker_build')==fingerprint() and runtime.get('updated_at') is not None
                   and 0 <= (now-utc(runtime['updated_at'])).total_seconds() < 30)
    return dict(settings=settings(),events=[json.loads(r[0]) for r in rows],sources=sources,
                block=entry_block(now),time=now.isoformat(),runtime_ready=runtime_ready,
                coverage='Fed and BEA schedules auto-refresh. BLS/CPI/jobs, Census, ISM, claims, auctions and earnings require reviewed manual entries. Unscheduled news is not covered.')


def refresh_if_due():
    if not settings()['enabled']: return
    with closing(connect()) as conn:
        rows=conn.execute('SELECT record FROM economic_calendar_sources').fetchall() if exists(conn,'economic_calendar_sources') else []
    now=datetime.now(timezone.utc)
    if not rows or any((now-utc(json.loads(r[0]).get('attempted_at','1970-01-01T00:00:00+00:00'))).total_seconds()>6*3600 for r in rows):
        refresh(now)
