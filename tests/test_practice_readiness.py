from copy import deepcopy
from dataclasses import asdict
from datetime import datetime,timedelta,timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from goxtrade.diagnostics import practice_readiness as readiness
from goxtrade.execution import practice_executor as executor
from goxtrade.execution.safeguards import Limits,PROTOCOL_VERSION


class PracticeReadinessTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,26,20,tzinfo=timezone.utc)
        self.state=dict(settings=dict(enabled=True,automation=dict(id='authorized',policy=dict(symbols=['MNQ']))),leader_settings=dict(enabled=False),
                        calendar=dict(valid=True,reason='Reviewed fixture'),market_open=True,
                        market_trades=dict(MNQ=dict(price=100.,event_time=self.now.isoformat(),received_at=self.now.isoformat())),
                        runtime=dict(account_id=41,updated_at=self.now.isoformat(),safeguards_version=PROTOCOL_VERSION,worker_build=readiness.fingerprint()),target=dict(id=41,gate_id=41),
                        limits=asdict(Limits()),gate=dict(account_id=41,locked=False,baseline=10000.,loss=0.,limit=500.),
                        health=dict(error=False,updated_at=self.now.isoformat(),positions=[],orders=[]),jobs=[])
        p=patch.object(executor,'ACCOUNT_ID',41);p.start();self.addCleanup(p.stop)

    def result(self):return readiness.assess(self.state,self.now)

    def test_flat_or_paused_ready_is_passive_and_preserves_settings(self):
        before=deepcopy(self.state)
        with patch.object(executor,'post',side_effect=AssertionError('No broker transport')):
            self.assertEqual(self.result()['status'],'CHECKS_PASSED')
        self.assertEqual(self.state,before)
        self.state['settings']['enabled']=False
        self.assertEqual(self.result()['status'],'CHECKS_PASSED')
        self.assertFalse(self.result()['entries_enabled'])

    def test_leader_or_old_worker_or_stale_heartbeat_block(self):
        self.state['leader_settings']['enabled']=True
        self.assertIn('leader_disabled',self.result()['blockers'])
        self.state['leader_settings']['enabled']=False
        self.state['runtime']['safeguards_version']='account-limits-v1'
        self.assertIn('current_worker',self.result()['blockers'])
        self.state['runtime']['safeguards_version']=PROTOCOL_VERSION
        self.state['runtime']['updated_at']=(self.now-timedelta(seconds=46)).isoformat()
        self.assertIn('current_worker',self.result()['blockers'])

    def test_source_upgrade_requires_worker_reload(self):
        self.state['runtime']['worker_build']='old-source-build'
        self.assertIn('current_worker',self.result()['blockers'])

    def test_calendar_expiry_and_stale_micro_trades_are_not_healthy(self):
        self.state['calendar']['valid']=False
        self.assertIn('reviewed_calendar',self.result()['blockers'])
        self.state['calendar']['valid']=True
        self.state['market_trades']['MNQ']['event_time']=(self.now-timedelta(seconds=31)).isoformat()
        self.assertIn('selected_market_data',self.result()['blockers'])
        self.state['market_open']=False
        self.assertNotIn('selected_market_data',self.result()['blockers'])

    def test_data_requires_all_selected_symbols_valid_prices_and_provider_time(self):
        self.state['settings']['automation']['policy']['symbols']=['MNQ','MES']
        self.assertIn('selected_market_data',self.result()['blockers'])
        self.state['market_trades']['MES']=deepcopy(self.state['market_trades']['MNQ'])
        self.assertEqual(self.result()['status'],'CHECKS_PASSED')
        for field,value in (('price',float('nan')),('price',-1),('received_at',None),('event_time',(self.now+timedelta(seconds=1)).isoformat())):
            with self.subTest(field=field,value=value):
                saved=deepcopy(self.state['market_trades']['MES'])
                self.state['market_trades']['MES'][field]=value
                self.assertIn('selected_market_data',self.result()['blockers'])
                self.state['market_trades']['MES']=saved

    def test_live_heartbeat_does_not_mask_stale_broker_or_loss_lock(self):
        self.state['health']['updated_at']=(self.now-timedelta(seconds=46)).isoformat()
        self.state['gate']['locked']=True
        self.assertIn('broker_reconciliation',self.result()['blockers'])
        self.assertIn('loss_lock',self.result()['blockers'])
        self.assertNotIn('current_worker',self.result()['blockers'])

    def open_position(self):
        self.state['jobs']=[dict(state='Open',symbol='MNQ',contract_id='CON.F.US.MNQ.Z26',quantity=2,side=0,order_id=10)]
        self.state['health']['positions']=[dict(accountId=41,contractId='CON.F.US.MNQ.Z26',size=2,type=1,averagePrice=100.)]
        self.state['health']['orders']=[dict(accountId=41,contractId='CON.F.US.MNQ.Z26',size=2,side=1,type=4,parentOrderId=10,stopPrice=90.)]

    def test_open_trade_requires_actual_matching_linked_broker_stop(self):
        self.open_position()
        self.assertEqual(self.result()['status'],'CHECKS_PASSED')
        self.state['health']['orders'][0]['parentOrderId']=99
        self.assertIn('owned_protected_exposure',self.result()['blockers'])

    def test_partial_fill_unknown_close_and_orphan_orders_block_new_entries(self):
        for mutation in ('partial','unknown','closing','orphan'):
            with self.subTest(mutation=mutation):
                self.open_position()
                if mutation=='partial':self.state['health']['positions'][0]['size']=1
                elif mutation=='unknown':self.state['jobs'][0]['state']='Unknown'
                elif mutation=='closing':self.state['jobs'][0]['state']='Closing'
                else:self.state['health']['positions']=[];self.state['jobs']=[]
                self.assertIn('owned_protected_exposure',self.result()['blockers'])

    def test_unavailable_database_is_not_created_or_repaired(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(readiness.live_store,'DB_PATH',Path(folder)/'absent.db'):
            self.assertEqual(readiness.collect()['blockers'],['local_evidence_unavailable'])
            self.assertFalse(readiness.live_store.DB_PATH.exists())

