import unittest
import tempfile
from contextlib import closing
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
import pandas as pd
import entry_confirmation as c
import live_store
import test_multi_symbol_entries as multi


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026,10,1,16,16,5,tzinfo=timezone.utc)
        self.signal = dict(id=1,symbol='NQ=F',status='Active',signal='LONG',signal_minutes=15,
                           setup_time='2026-10-01T16:00:00+00:00',entry=101.,target=110.,stop=90.,setup_invalidation=95.)
        self.bars = pd.DataFrame(dict(time=pd.date_range('2026-10-01T16:00:00Z',periods=16,freq='min'),
                                      open=100.,high=101.,low=99.,close=100.,volume=10.))
        self.bars.loc[14,['open','high','low','close']] = [100,102,99,101]
        self.bars.loc[15,['open','high','low','close']] = [101,103,100,103]

    def evaluate(self,price=103):
        return c.evaluate(self.signal,self.bars,price,self.now)

    def test_long_and_short(self):
        self.assertEqual(self.evaluate()['state'],'Confirmed')
        self.signal.update(signal='SHORT',entry=99,target=90,stop=110,setup_invalidation=105)
        for key in ['open','close','high','low']:
            self.bars[key] = 200-self.bars[key]
        self.bars[['high','low']] = self.bars[['low','high']].to_numpy()
        self.assertEqual(self.evaluate(97)['state'],'Confirmed')

    def test_wait_before_new_minute_and_weak_trigger(self):
        self.now = datetime(2026,10,1,16,15,5,tzinfo=timezone.utc)
        self.assertEqual(self.evaluate(101)['state'],'Waiting')
        self.now = datetime(2026,10,1,16,16,5,tzinfo=timezone.utc)
        self.assertEqual(self.evaluate(102)['state'],'Waiting')
        self.bars.loc[15,'close'] = 101
        self.assertEqual(self.evaluate(101)['state'],'Waiting')

    def test_5m_opposition_and_missing_data(self):
        self.bars.loc[14,'close'] = 99
        self.assertIn('5m',self.evaluate()['reason'])
        self.bars = self.bars.drop(index=12)
        self.assertEqual(self.evaluate()['state'],'Waiting')

    def test_cancel_expired_breached_and_chased(self):
        self.assertEqual(self.evaluate(95)['state'],'Cancelled')
        self.assertEqual(self.evaluate(105)['state'],'Waiting')
        self.bars.loc[15,'low'] = 94
        self.assertEqual(self.evaluate()['state'],'Cancelled')

    def test_cancel_is_durable_even_after_price_recovers(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(live_store,'DB_PATH',Path(directory)/'test.db'), patch.object(c,'chart_history',return_value=self.bars), patch.object(c,'contract_for_symbol',return_value='contract'):
            with closing(live_store.connect()) as conn:
                conn.execute("INSERT INTO live_ticks(symbol,contract_id,event_type,price,event_time,received_at) VALUES (?,?,?,?,?,?)",('NQ=F','contract','trade',94,self.now.isoformat(),self.now.isoformat()))
                conn.commit()
            self.assertEqual(c.check(self.signal,self.now)['state'],'Cancelled')
            with closing(live_store.connect()) as conn:
                conn.execute('UPDATE live_ticks SET price=103')
                conn.commit()
            self.assertEqual(c.check(self.signal,self.now)['state'],'Cancelled')
        self.now = datetime(2026,10,1,16,25,tzinfo=timezone.utc)
        self.assertFalse(c.window_open(self.signal,self.now))
        self.assertEqual(self.evaluate()['state'],'Cancelled')

    def test_practice_waits_for_pullback_but_leader_still_cancels(self):
        with patch.object(c, 'PROFILE', 'practice'):
            self.assertEqual(self.evaluate(105)['state'], 'Waiting')
            self.assertEqual(self.evaluate(103)['state'], 'Confirmed')
            self.assertTrue(c.window_open(self.signal, datetime(2026,10,1,16,20,tzinfo=timezone.utc)))
            self.assertFalse(c.window_open(self.signal, datetime(2026,10,1,16,25,tzinfo=timezone.utc)))
        with patch.object(c, 'PROFILE', 'leader'):
            self.assertEqual(self.evaluate(105)['state'], 'Cancelled')
            self.assertFalse(c.window_open(self.signal, datetime(2026,10,1,16,20,tzinfo=timezone.utc)))

    def test_first_post_setup_five_minute_close_can_confirm(self):
        self.bars.loc[14,'close'] = 99
        self.assertEqual(self.evaluate()['state'], 'Waiting')
        extra = pd.DataFrame(dict(time=pd.date_range('2026-10-01T16:16:00Z',periods=5,freq='min'),
                                  open=101.,high=102.,low=100.,close=101.,volume=10.))
        extra.loc[3,['open','high','low','close']] = [101,102,100,102]
        extra.loc[4,['open','high','low','close']] = [102,103,101,103]
        self.bars = pd.concat([self.bars,extra],ignore_index=True)
        self.now = datetime(2026,10,1,16,21,5,tzinfo=timezone.utc)
        with patch.object(c, 'PROFILE', 'practice'):
            self.assertEqual(self.evaluate()['state'], 'Confirmed')
        with patch.object(c, 'PROFILE', 'leader'):
            self.assertEqual(self.evaluate()['state'], 'Cancelled')

    def test_persisted_practice_wait_is_rechecked(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(live_store,'DB_PATH',Path(directory)/'test.db'), patch.object(c,'PROFILE','practice'), patch.object(c,'chart_history',return_value=self.bars), patch.object(c,'contract_for_symbol',return_value='contract'):
            with closing(live_store.connect()) as conn:
                conn.execute("INSERT INTO live_ticks(symbol,contract_id,event_type,price,event_time,received_at) VALUES (?,?,?,?,?,?)",('NQ=F','contract','trade',105,self.now.isoformat(),self.now.isoformat()))
                conn.commit()
            self.assertEqual(c.check(self.signal,self.now)['state'],'Waiting')
            with closing(live_store.connect()) as conn:
                conn.execute('UPDATE live_ticks SET price=103')
                conn.commit()
            self.assertEqual(c.check(self.signal,self.now)['state'],'Confirmed')


class IntegrationTests(unittest.TestCase):
    setUp = multi.MultiSymbolTests.setUp
    cycle_mocks = multi.MultiSymbolTests.cycle_mocks

    def test_wait_then_confirm_and_final_recheck(self):
        import practice_executor as e
        signal=dict(id=3,status='Active',symbol='NQ=F',strategy='CRT',signal='LONG',entry=100,stop=95,entry_time=datetime.now(timezone.utc).isoformat())
        self.cycle_mocks([], [signal])
        self.stack.enter_context(patch.object(e,'quote_fresh',return_value=True))
        self.stack.enter_context(patch.object(e,'read_status',return_value={}))
        self.stack.enter_context(patch.object(e,'call',return_value=dict(contracts=[dict(id='CON.F.US.MNQ.Z26',symbolId='F.US.MNQ',activeContract=True)])))
        with patch.object(c,'check',return_value=dict(state='Waiting',reason='1m trigger')),patch.object(e,'post') as api:
            e.cycle('test')
            api.assert_not_called()
            self.assertEqual(e.snapshot()[2],[])
        with patch.object(c,'check',side_effect=[dict(state='Confirmed',reason='break',price=101),dict(state='Cancelled',reason='Invalidated')]),patch.object(e,'post') as api:
            e.cycle('test')
            api.assert_not_called()
            self.assertIn('Invalidated',e.snapshot()[2][0]['error_message'])
