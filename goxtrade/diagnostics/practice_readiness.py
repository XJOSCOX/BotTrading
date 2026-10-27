"""Passive Practice operations evidence. Never authorizes orders or repairs state."""
from contextlib import closing
from datetime import datetime, timezone
import json
import math
import sqlite3

from goxtrade.config.execution_identity import current_targets
from goxtrade.data import live_store
from goxtrade.diagnostics.practice_validation import fresh
from goxtrade.execution.safeguards import Limits, PROTOCOL_VERSION
from goxtrade.runtime.build_identity import fingerprint


def assess(state, now):
    checks=[]
    def check(name, passed, detail):
        checks.append(dict(check=name,status='PASS' if passed else 'BLOCKED',detail=detail))
    settings,runtime=state['settings'],state['runtime']
    target=state['target']
    check('leader_disabled',state['leader_settings'].get('enabled') is False,'Leader must remain explicitly disabled for Practice-only operation.')
    check('current_worker',runtime.get('safeguards_version')==PROTOCOL_VERSION and runtime.get('worker_build')==fingerprint() and runtime.get('account_id')==target['id'] and fresh(runtime.get('updated_at'),now,45),'Exact-account heartbeat must be fresh and its source build and safeguard protocol must match the installed code.')
    health=state['health']
    broker_fresh=health.get('error') is False and fresh(health.get('updated_at'),now,45)
    check('broker_reconciliation',broker_fresh,'Evidence is the worker’s last successful broker read, not a new broker request.')
    limits=Limits.parse(state['limits'])
    gate=state['gate']
    check('loss_lock',gate.get('account_id')==target['gate_id'] and gate.get('locked') is False and gate.get('limit')==limits.loss_lock and type(gate.get('baseline')) in (int,float) and math.isfinite(gate['baseline']) and type(gate.get('loss')) in (int,float) and 0<=gate['loss']<limits.loss_lock,'Saved active account limit applies; this check never resets the baseline or unlocks losses.')
    positions,orders=health.get('positions',[]),health.get('orders',[])
    jobs=[j for j in state['jobs'] if j.get('state') not in ('Closed','Rejected')]
    from goxtrade.execution.practice_executor import protective_order
    owned=True
    for position in positions:
        owned=owned and position.get('accountId')==target['id']
        owners=[j for j in jobs if j.get('contract_id')==position.get('contractId')]
        owned=owned and len(owners)==1
        if len(owners)==1:
            job=owners[0]
            owned=owned and job.get('state')=='Open' and position.get('size')==job.get('quantity') and position.get('type')==job.get('side',-2)+1 and any(protective_order(order,job) for order in orders)
    owned=owned and len(positions)==len(jobs) and all(any(protective_order(order,j) for j in jobs) for order in orders)
    check('owned_protected_exposure',broker_fresh and owned,'Open positions require matching bot ownership and linked broker stops; pending/unknown outcomes and orphan orders block new entries.')
    check('execution_session',settings.get('enabled') is not True or bool(settings.get('automation') or settings.get('strategy_testing')),'Enabled Practice entries require an authorized saved strategy session.')
    calendar=state.get('calendar',{})
    check('reviewed_calendar',calendar.get('valid') is True,calendar.get('reason','Reviewed calendar evidence unavailable.'))
    session=settings.get('automation') or settings.get('strategy_testing') or {}
    symbols=(session.get('policy') or {}).get('symbols') or []
    data_required=settings.get('enabled') is True and state.get('market_open') is True
    trades=state.get('market_trades',{})
    data_ok=bool(symbols) and all(symbol in ('MNQ','MES','MYM') and
        fresh(trades.get(symbol,{}).get('event_time'),now,30) and
        fresh(trades.get(symbol,{}).get('received_at'),now,30) and
        type(trades.get(symbol,{}).get('price')) in (int,float) and
        math.isfinite(trades[symbol]['price']) and trades[symbol]['price']>0 for symbol in symbols)
    check('selected_market_data',not data_required or data_ok,
          'Selected micro contracts require valid provider trade timestamps and receipt timestamps within 30 seconds while enabled and the reviewed market is open. Individual strategies can require fresher data.')
    blocked=[r['check'] for r in checks if r['status']!='PASS']
    return dict(observed_at=now.isoformat(),scope='PASSIVE_PRACTICE_OPERATIONS',status='BLOCKED' if blocked else 'CHECKS_PASSED',checks=checks,blockers=blocked,
                entries_enabled=settings.get('enabled') is True,orders_submitted=0,
                limitation='Snapshot evidence, not certification of future fills, outage recovery or sustained unattended operation. Strategy, schedule, calendar, data and risk gates still decide each entry.')


def collect(now=None):
    try:
        now=now or datetime.now(timezone.utc)
        from goxtrade.market.calendar_guard import review_status
        from goxtrade.market.market_session import market_session
        from goxtrade.execution.contracts import contract_for_symbol
        from goxtrade.data.price_ticks import price_predicate
        calendar=review_status(now)
        target=current_targets()['practice']
        with closing(sqlite3.connect(live_store.DB_PATH.as_uri()+'?mode=ro',uri=True,timeout=2)) as conn:
            def control(profile):
                row=conn.execute(f'SELECT settings,status FROM {profile}_control WHERE id=1').fetchone()
                return (json.loads(row[0]),json.loads(row[1])) if row else ({},{})
            settings,runtime=control('practice')
            leader,_=control('leader')
            def record(table,account):
                row=conn.execute(f'SELECT record FROM {table} WHERE id=?',(account,)).fetchone()
                return json.loads(row[0]) if row else {}
            row=conn.execute('SELECT active FROM account_safeguards WHERE account_id=?',(target['gate_id'],)).fetchone()
            state=dict(settings=settings,runtime=runtime,leader_settings=leader,target=target,
                       limits=json.loads(row[0]) if row else {},gate=record('practice_loss_gate',target['gate_id']),
                       health=record('bot_health',target['gate_id']),jobs=[json.loads(row[0]) for row in conn.execute('SELECT record FROM practice_jobs')])
            trades={}
            session=settings.get('automation') or settings.get('strategy_testing') or {}
            for symbol in (session.get('policy') or {}).get('symbols',[]):
                if symbol not in ('MNQ','MES','MYM'):
                    continue
                row=conn.execute("SELECT price,event_time,received_at FROM live_ticks WHERE symbol=? AND contract_id=? "
                                 f"AND event_type='trade' AND {price_predicate(symbol+'=F')} ORDER BY id DESC LIMIT 1",
                                 (symbol+'=F',contract_for_symbol(symbol+'=F'))).fetchone()
                if row:
                    trades[symbol]=dict(zip(('price','event_time','received_at'),row))
            state.update(calendar=calendar,market_open=market_session(now)['is_open'] and calendar['currently_open'],market_trades=trades)
        return assess(state,now)
    except (OSError,sqlite3.Error,ValueError,TypeError,KeyError):
        return dict(status='BLOCKED',scope='PASSIVE_PRACTICE_OPERATIONS',checks=[],blockers=['local_evidence_unavailable'],orders_submitted=0,
                    limitation='Read-only evidence unavailable or invalid. No settings, broker state or process registrations were changed.')
