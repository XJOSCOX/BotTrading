"""Watch lifecycle maintenance, serialized with execution claims."""
import json
from contextlib import closing
from datetime import datetime, timezone
from goxtrade.data.live_store import connect


def reconcile_closed_trades(profile, account_id):
    """Release only proven closed broker ownership; never consume a new signal."""
    from goxtrade.execution.executed_results import results
    if profile not in ('practice','leader'):
        raise ValueError('Unknown account profile')
    with closing(connect()) as conn:
        tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'bot_alert_history' not in tables or profile+'_jobs' not in tables:
            return 0
        conn.execute('BEGIN IMMEDIATE')
        pending=conn.execute(f"""SELECT j.record,h.record FROM {profile}_jobs j
            JOIN bot_alert_history h ON h.id=j.alert_id
            WHERE json_extract(j.record,'$.state')='Closed'
            AND (json_extract(h.record,'$.status')='Active' OR
              (json_extract(h.record,'$.exit_source')='broker' AND
               (json_extract(h.record,'$.exit_price') IS NULL OR json_extract(h.record,'$.exit_time') IS NULL)))""").fetchall()
        if not pending:
            return 0
        jobs=[json.loads(r[0]) for r in pending]
        jobs=[j for j in jobs if j.get('account_id')==account_id and j.get('closed_confirmed_at') and j.get('fill_price') and j.get('order_id') and j.get('alert_id',-1)>=0]
        if not jobs:
            return 0
        fills=[json.loads(r[0]) for r in conn.execute(f'SELECT record FROM {profile}_fills')] if profile+'_fills' in tables else []
        matched=results(jobs,fills)
        count=0
        for job in jobs:
            alert_id=job['alert_id']
            owned=False
            for other in ('practice','leader'):
                if other+'_jobs' in tables:
                    row=conn.execute(f'SELECT record FROM {other}_jobs WHERE alert_id=?',(alert_id,)).fetchone()
                    if row and json.loads(row[0]).get('state') not in ('Closed','Rejected'):
                        owned=True
            if owned:
                continue
            row=conn.execute('SELECT record FROM bot_alert_history WHERE id=?',(alert_id,)).fetchone()
            if not row:
                continue
            record=json.loads(row[0])
            if record.get('status')!='Active' and record.get('exit_source')!='broker':
                continue
            actual=matched.get(alert_id,{})
            updates=dict(status='Closed',exit_reason='Broker position closed',exit_source='broker',
                         broker_close_confirmed_at=job['closed_confirmed_at'],
                         exit_price=actual.get('exit_price'),exit_time=actual.get('closed_at'))
            if any(record.get(k)!=v for k,v in updates.items()):
                record.update(updates)
                conn.execute('UPDATE bot_alert_history SET record=? WHERE id=?',(json.dumps(record),alert_id))
                count+=1
            if 'signal_lifecycle' in tables:
                row=conn.execute('SELECT state FROM signal_lifecycle WHERE symbol=? AND strategy=?',(record['symbol'],record['strategy'])).fetchone()
                if row:
                    state=json.loads(row[0])
                    if state.get('event_id')==alert_id:
                        state.update(active=None,event_id=None,exit='Broker position closed')
                        conn.execute('UPDATE signal_lifecycle SET state=? WHERE symbol=? AND strategy=?',(json.dumps(state),record['symbol'],record['strategy']))
        conn.commit()
        return count


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
