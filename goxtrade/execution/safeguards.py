"""Account-specific persisted limits. Saving never arms trading or clears losses."""
from contextlib import closing
from dataclasses import asdict,dataclass
from datetime import datetime,timezone
import json
import math

from goxtrade.data.live_store import connect

PROTOCOL_VERSION='account-limits-v2'


@dataclass(frozen=True)
class Limits:
    loss_lock: float = 500.
    max_contracts: int = 4
    max_trade_risk: float = 75.
    max_open_risk: float = 150.
    overnight_max_contracts: int = 1
    overnight_cooldown_minutes: int = 15
    overnight_max_spread_ticks: int = 2

    @classmethod
    def parse(cls, values):
        required={'loss_lock','max_contracts','max_trade_risk','max_open_risk'}
        if not isinstance(values,dict) or not required<=set(values) or set(values)-set(cls.__dataclass_fields__):
            raise ValueError("Enter all supported safeguard settings")
        # Older saved rows retain their original bytes/revision and prior night behavior.
        values=asdict(cls(**values))
        if type(values['max_contracts']) is not int or not 1<=values['max_contracts']<=4:
            raise ValueError("Contract maximum must be within the supported 1-4 range")
        for name in ('loss_lock','max_trade_risk','max_open_risk'):
            value=values[name]
            if type(value) not in (int,float) or not math.isfinite(value) or not 0<value<=1000000:
                raise ValueError(f"{name} must be a finite positive dollar value")
        if not values['max_trade_risk']<=values['max_open_risk']<=values['loss_lock']:
            raise ValueError("Trade risk must not exceed open risk, and open risk must not exceed the account loss lock")
        for field,minimum,maximum in (('overnight_max_contracts',1,4),('overnight_cooldown_minutes',0,1440),('overnight_max_spread_ticks',1,100)):
            if type(values[field]) is not int or not minimum<=values[field]<=maximum:
                raise ValueError(f'{field} must be an integer from {minimum} to {maximum}')
        return cls(**values)


def initialize(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS account_safeguards (account_id INTEGER PRIMARY KEY,saved TEXT NOT NULL,active TEXT NOT NULL,revision INTEGER NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS safeguard_audit (id INTEGER PRIMARY KEY,account_id INTEGER,time TEXT,action TEXT,record TEXT)")


def _read(conn, account_id):
    initialize(conn)
    row=conn.execute("SELECT saved,active,revision FROM account_safeguards WHERE account_id=?",(account_id,)).fetchone()
    if row:
        return dict(saved=asdict(Limits.parse(json.loads(row[0]))),active=asdict(Limits.parse(json.loads(row[1]))),revision=row[2])
    defaults=asdict(Limits())
    conn.execute("INSERT OR IGNORE INTO account_safeguards VALUES (?,?,?,0)",(account_id,json.dumps(defaults),json.dumps(defaults)))
    return dict(saved=defaults.copy(),active=defaults.copy(),revision=0)


def read(account_id,conn=None):
    if conn is not None:
        return _read(conn,account_id)
    with closing(connect()) as own:
        record=_read(own,account_id);own.commit()
        return record


def active(account_id,conn=None):
    return Limits.parse(read(account_id,conn)['active'])


def save(account_id,values,revision):
    values=asdict(Limits.parse(values))
    with closing(connect()) as conn:
        initialize(conn);conn.commit();conn.execute('BEGIN IMMEDIATE')
        current=_read(conn,account_id)
        if current['revision']!=revision:
            raise ValueError("Safeguards changed elsewhere; reload before saving")
        conn.execute('UPDATE account_safeguards SET saved=?,revision=revision+1 WHERE account_id=?',(json.dumps(values),account_id))
        _audit(conn,account_id,'saved',values);conn.commit()
    return read(account_id)


def _audit(conn,account_id,action,values):
    conn.execute('INSERT INTO safeguard_audit(account_id,time,action,record) VALUES (?,?,?,?)',
                 (account_id,datetime.now(timezone.utc).isoformat(),action,json.dumps(values)))


def apply(profile,confirmed_name,revision):
    from goxtrade.config import execution_identity as identity
    from goxtrade.execution import projectx_client
    from goxtrade.execution.live_accounts import copy_role
    if profile not in ('practice','leader'):
        raise ValueError('Unknown execution profile')
    identity.assert_current(profile)
    target=identity.current_targets()[profile]
    if confirmed_name!=target['name']:
        raise ValueError('Confirm the exact account before applying safeguards')
    def paused(conn):
        if conn.execute('SELECT 1 FROM sqlite_master WHERE name=?',(profile+'_control',)).fetchone():
            row=conn.execute(f'SELECT settings,status FROM {profile}_control WHERE id=1').fetchone()
            if row and json.loads(row[0]).get('enabled'):
                raise ValueError('Pause new entries before applying safeguards')
            runtime=json.loads(row[1]) if row else {}
            try:
                age=(datetime.now(timezone.utc)-datetime.fromisoformat(runtime['updated_at'])).total_seconds()
            except (ValueError,KeyError,TypeError):
                age=float('inf')
            if runtime.get('safeguards_version')!=PROTOCOL_VERSION or runtime.get('account_id')!=target['id'] or not 0<=age<45:
                raise ValueError('Start or restart the updated account worker before applying safeguards')
        else:
            raise ValueError('Start the account worker before applying safeguards')
        if conn.execute('SELECT 1 FROM sqlite_master WHERE name=?',(profile+'_jobs',)).fetchone():
            if any(json.loads(r[0]).get('state') not in ('Closed','Rejected') for r in conn.execute(f'SELECT record FROM {profile}_jobs')):
                raise ValueError('Resolve broker jobs before applying safeguards')
    with closing(connect()) as conn:
        paused(conn)
    token=projectx_client.login()
    result=projectx_client.post('/api/Account/search',dict(onlyActiveAccounts=False),token)
    account=next((a for a in result.get('accounts',[]) if a.get('id')==target['id']),{})
    if (result.get('success') is not True or account.get('name')!=target['name'] or account.get('canTrade') is not True
            or account.get('simulated') is not True or copy_role(account)!=target['role']):
        raise ValueError('Exact broker account could not be verified')
    if type(account.get('balance')) not in (int,float) or not math.isfinite(account['balance']):
        raise ValueError('Verified account balance is required to apply safeguards')
    for path,key in (('/api/Position/searchOpen','positions'),('/api/Order/searchOpen','orders')):
        result=projectx_client.post(path,dict(accountId=target['id']),token)
        if result.get('success') is not True or not isinstance(result.get(key),list) or result[key]:
            raise ValueError('Account must be verified flat with no working orders')
    identity.assert_current(profile)
    from goxtrade.execution.practice_safety import check
    check(account['balance'],account_id=target['gate_id'])
    with closing(connect()) as conn:
        initialize(conn);conn.commit();conn.execute('BEGIN IMMEDIATE');paused(conn)
        current=_read(conn,target['gate_id'])
        if current['revision']!=revision:
            raise ValueError('Safeguards changed during verification; review and apply again')
        conn.execute('UPDATE account_safeguards SET active=saved,revision=revision+1 WHERE account_id=?',(target['gate_id'],))
        gate_row=conn.execute('SELECT record FROM practice_loss_gate WHERE id=?',(target['gate_id'],)).fetchone()
        gate=json.loads(gate_row[0])
        gate['limit']=current['saved']['loss_lock']
        gate['locked']=gate['locked'] or gate['loss']>=gate['limit']
        conn.execute('UPDATE practice_loss_gate SET record=? WHERE id=?',(json.dumps(gate),target['gate_id']))
        _audit(conn,target['gate_id'],'applied',dict(previous=current['active'],active=current['saved']));conn.commit()
    return read(target['gate_id'])
