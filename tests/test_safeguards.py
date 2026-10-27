from contextlib import closing
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
from datetime import datetime,timezone
import unittest
from unittest.mock import patch

from goxtrade.data import live_store
from goxtrade.config import execution_identity as identity
from goxtrade.execution import safeguards as sg,practice_safety,practice_executor as executor,projectx_client
from goxtrade.runtime.build_identity import fingerprint


TARGETS=dict(practice=dict(id=41,gate_id=41,name='PRAC-GUARDS-FIXTURE',role='Not assigned'),
             leader=dict(id=42,gate_id=42,name='LEADER-GUARDS-FIXTURE',role='Leader'))


class SafeguardTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        for p in (patch.object(live_store,'DB_PATH',Path(folder.name)/'guards.db'),
                  patch.object(identity,'current_targets',return_value=TARGETS),patch.object(identity,'assert_current'),
                  patch.object(executor,'TARGET',TARGETS['practice']),patch.object(executor,'PROFILE','practice')):
            p.start();self.addCleanup(p.stop)
        with closing(executor.db()) as conn:
            conn.execute("UPDATE practice_control SET settings=?,status=? WHERE id=1",(json.dumps(dict(enabled=False)),json.dumps(dict(safeguards_version=sg.PROTOCOL_VERSION,worker_build=fingerprint(),account_id=41,updated_at=datetime.now(timezone.utc).isoformat()))));conn.commit()
        self.balance=10000.

    def provider(self,path,payload,token=None):
        if path=='/api/Account/search':
            return dict(success=True,accounts=[dict(id=t['id'],name=t['name'],balance=self.balance,canTrade=True,simulated=True) for t in TARGETS.values()])
        return dict(success=True,positions=[],orders=[])

    def apply(self,profile='practice',revision=1):
        with patch.object(projectx_client,'login',return_value='fixture'),patch.object(projectx_client,'post',side_effect=self.provider),patch('goxtrade.execution.live_accounts.copy_role',side_effect=lambda a:TARGETS['practice' if a['id']==41 else 'leader']['role']):
            return sg.apply(profile,TARGETS[profile]['name'],revision)

    def save(self,account=41,**changes):
        record=sg.read(account)
        return sg.save(account,{**record['saved'],**changes},record['revision'])

    def test_save_persists_without_apply_or_cross_account_changes(self):
        old=sg.read(41);other=sg.read(42)
        record=self.save(loss_lock=1000,max_contracts=2,max_trade_risk=100,max_open_risk=200)
        self.assertEqual(record['active'],old['active'])
        self.assertEqual(sg.read(41),record)
        self.assertEqual(sg.read(42),other)
        self.assertFalse(executor.snapshot()[0]['enabled'])
        with self.assertRaises(ValueError):sg.save(41,record['saved'],0)

    def test_leader_safeguards_are_separate_and_do_not_enable_leader(self):
        with closing(executor.db()) as conn:
            conn.execute('CREATE TABLE leader_control(id INTEGER PRIMARY KEY,settings TEXT,status TEXT)')
            conn.execute('INSERT INTO leader_control VALUES(1,?,?)',(json.dumps(dict(enabled=False)),json.dumps(dict(safeguards_version=sg.PROTOCOL_VERSION,worker_build=fingerprint(),account_id=42,updated_at=datetime.now(timezone.utc).isoformat()))));conn.commit()
        original=sg.read(41)
        self.save(account=42,loss_lock=1000,max_contracts=2)
        self.apply(profile='leader')
        self.assertEqual(sg.active(42).loss_lock,1000)
        self.assertEqual(sg.read(41),original)
        with closing(executor.db()) as conn:
            self.assertFalse(json.loads(conn.execute('SELECT settings FROM leader_control').fetchone()[0])['enabled'])

    def test_old_worker_cannot_apply_new_limits(self):
        self.save(max_contracts=2)
        with closing(executor.db()) as conn:
            conn.execute("UPDATE practice_control SET status='{}'");conn.commit()
        with patch.object(projectx_client,'login') as login:
            with self.assertRaises(ValueError):sg.apply('practice',TARGETS['practice']['name'],1)
        login.assert_not_called()

    def test_apply_higher_preserves_baseline_latched_lock_and_paused_state(self):
        practice_safety.check(10000,account_id=41)
        self.balance=9400
        self.assertTrue(practice_safety.check(self.balance,account_id=41)['locked'])
        self.save(loss_lock=1000,max_trade_risk=100,max_open_risk=200)
        self.apply()
        gate=practice_safety.check(self.balance,account_id=41)
        self.assertEqual((gate['baseline'],gate['loss'],gate['limit']),(10000,600,1000))
        self.assertTrue(gate['locked'])
        self.assertFalse(executor.snapshot()[0]['enabled'])

    def test_lowering_limit_latches_existing_loss_without_baseline_reset(self):
        practice_safety.check(10000,account_id=41);self.balance=9650
        self.save(loss_lock=300)
        self.apply()
        gate=practice_safety.snapshot(41)
        self.assertTrue(gate['locked']);self.assertEqual(gate['baseline'],10000)

    def test_apply_requires_exact_account_paused_flat_and_current_revision(self):
        self.save(max_contracts=2)
        with self.assertRaises(ValueError):sg.apply('practice','OTHER',1)
        executor.update_settings(enabled=True)
        with self.assertRaises(ValueError):self.apply()
        executor.update_settings(enabled=False)
        with self.assertRaises(ValueError):self.apply(revision=0)
        with patch.object(projectx_client,'login',return_value='fixture'),patch.object(projectx_client,'post',side_effect=lambda path,*a,**k:self.provider(path,*a,**k) if path=='/api/Account/search' else dict(success=True,positions=[dict(id=1)],orders=[])),patch('goxtrade.execution.live_accounts.copy_role',return_value='Not assigned'):
            with self.assertRaises(ValueError):sg.apply('practice',TARGETS['practice']['name'],1)
        self.assertEqual(sg.active(41).max_contracts,4)

    def test_order_send_enforces_contract_stop_risk_and_account_headroom(self):
        self.save(max_contracts=1,max_trade_risk=50,max_open_risk=100);self.apply()
        order=dict(contractId='CON.F.US.MNQ.Z26',size=1,stopLossBracket=dict(ticks=-40))
        self.assertEqual(executor.check_order_safeguards(order,dict(loss=0,locked=False)),20)
        for payload,gate in (({**order,'size':2},dict(loss=0)),({**order,'stopLossBracket':dict(ticks=-120)},dict(loss=0)),(order,dict(loss=490))):
            with self.assertRaises(ValueError):executor.check_order_safeguards(payload,gate)

    def test_explicitly_applied_higher_limit_is_enforced_instead_of_old_fixed_value(self):
        self.save(loss_lock=1000,max_trade_risk=100,max_open_risk=200);self.apply()
        gate=practice_safety.check(9400,account_id=41)
        self.assertEqual(gate['limit'],1000)
        self.assertFalse(gate['locked'])
        self.assertEqual(gate['baseline'],10000)
        order=dict(contractId='CON.F.US.MNQ.Z26',size=1,stopLossBracket=dict(ticks=-120))
        self.assertEqual(executor.check_order_safeguards(order,gate),60)

    def test_total_open_risk_includes_existing_verified_positions(self):
        self.save(max_trade_risk=90,max_open_risk=100);self.apply()
        position=dict(contractId='CON.F.US.MNQ.Z26',averagePrice=100.,size=1)
        job=dict(symbol='MNQ',state='Open',contract_id=position['contractId'],side=0,quantity=1,order_id=9)
        stop=dict(parentOrderId=9,contractId=position['contractId'],type=4,side=1,size=1,stopPrice=60.)
        order=dict(contractId='CON.F.US.MES.Z26',size=1,stopLossBracket=dict(ticks=-20))
        with self.assertRaisesRegex(ValueError,'total open'):
            executor.check_order_safeguards(order,dict(loss=0),[position],[stop],[job])

    def test_invalid_values_and_inconsistent_budgets_fail_closed(self):
        for changes in (dict(loss_lock=True),dict(loss_lock=float('nan')),dict(max_contracts=5),dict(max_contracts=True),dict(max_trade_risk=200),dict(max_open_risk=600),dict(unknown=1),dict(overnight_max_contracts=5),dict(overnight_max_contracts=True),dict(overnight_cooldown_minutes=-1),dict(overnight_max_spread_ticks=0),dict(overnight_max_spread_ticks=1.5)):
            with self.assertRaises(ValueError):sg.Limits.parse({**asdict(sg.Limits()),**changes})

    def test_legacy_rows_get_old_night_defaults_without_rewriting_saved_bytes(self):
        old=dict(loss_lock=500.,max_contracts=3,max_trade_risk=250.,max_open_risk=500.)
        with closing(executor.db()) as conn:
            conn.execute('INSERT INTO account_safeguards VALUES (?,?,?,7)',(41,json.dumps(old),json.dumps(old)));conn.commit()
            before=tuple(conn.execute('SELECT saved,active,revision FROM account_safeguards WHERE account_id=41').fetchone())
        normalized=sg.read(41)
        self.assertEqual(normalized['saved'],{**old,'overnight_max_contracts':1,'overnight_cooldown_minutes':15,'overnight_max_spread_ticks':2})
        with closing(executor.db()) as conn:
            self.assertEqual(tuple(conn.execute('SELECT saved,active,revision FROM account_safeguards WHERE account_id=41').fetchone()),before)


if __name__=='__main__':unittest.main()
