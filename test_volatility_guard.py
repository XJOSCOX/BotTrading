import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import live_store
import volatility_guard as guard
import test_multi_symbol_entries as multi


class VolatilityTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026,9,29,15,0,2,tzinfo=timezone.utc)
        self.frame = pd.DataFrame(dict(time=pd.date_range(end=pd.Timestamp(self.now).floor('min'),periods=241,freq='min'),
                                       open=100.,high=101.,low=99.,close=100.,volume=100.))
        self.quote = dict(contract_id='micro',best_bid=100.,best_ask=100.25,last_price=100.,
                          event_time=self.now.isoformat(),received_at=self.now.isoformat())

    def assess(self, price=None):
        return guard.assess(self.frame,self.quote,'NQ=F','micro',self.now,price)

    def test_normal_and_live_spike(self):
        self.assertEqual(self.assess(),(None,False))
        reason,shock = self.assess(110.)
        self.assertTrue(shock)
        self.assertIn('1m move',reason)

    def test_forming_and_completed_minute_spikes(self):
        for idx in [239,240]:
            with self.subTest(idx=idx):
                self.frame.loc[idx,'high'] = 110.
                self.assertTrue(self.assess()[1])
                self.frame.loc[idx,'high'] = 101.

    def test_large_completed_15m_candle(self):
        # A gradual large move avoids the separate minute-range trigger.
        for idx in range(225,240):
            value = 100+(idx-225)*.5
            self.frame.loc[idx,['open','high','low','close']] = [value,value+1,value-1,value]
        self.frame.loc[240,['open','high','low','close']] = [107,108,106,107]
        reason,shock = self.assess()
        self.assertTrue(shock)
        self.assertIn('15m range',reason)

    def test_spread_and_missing_data(self):
        self.quote['best_ask'] = 101.25
        self.assertTrue(self.assess()[1])
        self.quote['best_ask'] = 100.25
        self.quote['best_bid'] = None
        self.assertIn('two-sided',self.assess()[0])
        self.quote['best_bid'] = 100.
        self.frame = self.frame.drop(index=230)
        self.assertIn('incomplete',self.assess()[0])

    def test_stale_and_wrong_contract(self):
        self.quote['event_time'] = (self.now-timedelta(seconds=11)).isoformat()
        self.assertIn('stale',self.assess()[0])
        self.quote['contract_id'] = 'other'
        self.assertIn('matching',self.assess()[0])

    def test_persistent_hold_and_extension(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(live_store,'DB_PATH',Path(directory)/'test.db'):
            guard.record_check('NQ=F','spike',True,self.now)
            self.assertIn('cooldown',guard.record_check('NQ=F',None,False,self.now+timedelta(seconds=299)))
            self.assertIsNone(guard.record_check('ES=F',None,False,self.now))
            guard.record_check('NQ=F','spread',True,self.now+timedelta(seconds=290))
            self.assertIn('cooldown',guard.record_check('NQ=F',None,False,self.now+timedelta(seconds=301)))
            self.assertIsNone(guard.record_check('NQ=F',None,False,self.now+timedelta(seconds=591)))


class EntryIntegrationTests(unittest.TestCase):
    setUp = multi.MultiSymbolTests.setUp
    cycle_mocks = multi.MultiSymbolTests.cycle_mocks

    def test_first_and_final_checks_prevent_submission(self):
        import practice_executor as e
        signal=dict(id=3,status='Active',symbol='NQ=F',strategy='CRT',signal='LONG',entry=100,stop=95,entry_time=datetime.now(timezone.utc).isoformat())
        self.cycle_mocks([], [signal])
        self.stack.enter_context(patch.object(e,'quote_fresh',return_value=True))
        self.stack.enter_context(patch.object(e,'read_status',return_value={}))
        self.stack.enter_context(patch.object(e,'call',return_value=dict(contracts=[dict(id='CON.F.US.MNQ.Z26',symbolId='F.US.MNQ',activeContract=True)])))
        with patch('volatility_guard.entry_block',return_value='Volatility guard: spike'),patch.object(e,'post') as api:
            e.cycle('test')
            api.assert_not_called()
            self.assertEqual(e.snapshot()[2],[])
        with patch('volatility_guard.entry_block',side_effect=[None,'Volatility guard: spread']),patch.object(e,'post') as api:
            e.cycle('test')
            api.assert_not_called()
            self.assertIn('Volatility guard',e.snapshot()[2][0]['error_message'])
