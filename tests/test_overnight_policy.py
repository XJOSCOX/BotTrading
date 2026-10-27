import unittest
from datetime import datetime
from unittest.mock import patch
import pandas as pd
from goxtrade.strategies import overnight_policy as p
from goxtrade.market.market_session import CENTRAL
from tests import test_multi_symbol_entries as multi
from tests.test_multi_symbol_entries import job
from goxtrade.execution.safeguards import Limits


class OvernightTests(unittest.TestCase):
    def setUp(self):
        limits=patch.object(p,'active_limits',return_value=Limits())
        limits.start();self.addCleanup(limits.stop)
        self.now = datetime(2026, 9, 24, 7, 0, 2, tzinfo=CENTRAL)
        self.end = pd.Timestamp(self.now).tz_convert('UTC').floor('15min')-pd.Timedelta(minutes=15)
        self.bars = pd.DataFrame(dict(time=pd.date_range(end=self.end, periods=52, freq='15min'),
                                      close=range(100,152), volume=[100]*52))
        self.signal = dict(symbol='NQ=F',signal='LONG',strategy='CRT',status='Active',
                           signal_minutes=15,setup_time=self.end.isoformat())
        self.history = [self.signal,dict(self.signal,strategy='EMA Pullback')]
        self.quote = dict(contract_id='micro',best_bid=151.,best_ask=151.25,
                          event_time=self.now.isoformat(),received_at=self.now.isoformat())

    def result(self):
        return p.evaluate(self.signal,self.history,{'CRT','EMA Pullback'},self.bars,self.quote,'micro',self.now)

    def test_confirmed_long_and_short(self):
        self.assertIsNone(self.result())
        self.bars['close'] = list(reversed(range(100,152)))
        for row in self.history:
            row['signal'] = 'SHORT'
        self.assertIsNone(self.result())

    def test_boundaries_and_caps(self):
        for hour,minute,expected in [(16,59,False),(17,0,True),(8,29,True),(8,30,False)]:
            now = self.now.replace(hour=hour,minute=minute)
            self.assertEqual(p.overnight(now),expected)
            self.assertEqual(p.quantity(3,now),1 if expected else 3)
            self.assertEqual(p.cooldown_seconds(300,now),900 if expected else 300)

    def test_effective_manager_policy_preserves_saved_values_and_daytime(self):
        from goxtrade.execution.execution_policy import ExecutionPolicy
        policy=ExecutionPolicy(requested_quantity=3,max_contracts=3,symbol_quantities=(('MNQ',3),('MES',2)))
        before=policy.to_dict()
        effective=p.effective_policy(policy,self.now,limits=Limits(max_contracts=2,overnight_max_contracts=3))
        self.assertEqual((effective.max_contracts,effective.requested_quantity,effective.cooldown_minutes),(2,2,15))
        self.assertEqual(effective.symbol_quantities,(('MNQ',2),('MES',2)))
        self.assertEqual(policy.to_dict(),before)
        self.assertIs(p.effective_policy(policy,self.now.replace(hour=10)),policy)

    def test_single_strategy_allowed_but_current_and_enabled_required(self):
        self.history = [self.signal]
        self.assertIsNone(self.result())
        original = self.signal.copy()
        for changes in [dict(strategy='Disabled'),dict(status='Closed'),dict(signal_minutes=1),
                        dict(setup_time=(self.end-pd.Timedelta(minutes=15)).isoformat())]:
            with self.subTest(changes=changes):
                self.signal = dict(original,**changes)
                self.assertIn('enabled strategy',self.result())

    def test_opposing_enabled_strategy_still_blocks(self):
        self.history[1]['signal'] = 'SHORT'
        self.assertIn('conflicting',self.result())

    def test_scheduled_break_allowed_but_open_market_gap_rejected(self):
        self.now = datetime(2026,9,24,20,0,2,tzinfo=CENTRAL)
        self.end = pd.Timestamp(self.now).tz_convert('UTC').floor('15min')-pd.Timedelta(minutes=15)
        stamps = pd.date_range(end=self.end,periods=56,freq='15min')
        stamps = [s for s in stamps if p.market_session(s.to_pydatetime())['is_open']]
        self.bars['time'] = stamps
        self.signal['setup_time'] = self.end.isoformat()
        self.history = [self.signal]
        self.quote.update(event_time=self.now.isoformat(),received_at=self.now.isoformat())
        self.assertIsNone(self.result())
        self.bars.loc[1,'time'] = self.bars.loc[0,'time']
        self.assertIn('missing open-market',self.result())

    def test_missing_trend_and_volume(self):
        self.bars.loc[20,'time'] += pd.Timedelta(minutes=1)
        self.assertIn('52 current',self.result())
        self.bars.loc[20,'time'] -= pd.Timedelta(minutes=1)
        self.bars.loc[51,'volume'] = 99
        self.assertIn('below',self.result())
        self.bars.loc[51,'volume'] = float('nan')
        self.assertIn('invalid',self.result())

    def test_micro_quote_validation(self):
        original = self.quote.copy()
        for changes in [dict(contract_id='mini'),dict(best_ask=152),dict(best_bid=151.25),
                        dict(best_bid=float('nan')),dict(best_ask=151.3),dict(event_time='bad'),
                        dict(received_at=(pd.Timestamp(self.now)-pd.Timedelta(seconds=11)).isoformat())]:
            with self.subTest(changes=changes):
                self.quote = dict(original,**changes)
                self.assertIsNotNone(self.result())

    def test_daytime_bypasses_filter(self):
        self.now = self.now.replace(hour=10)
        self.bars = pd.DataFrame()
        self.history = []
        self.assertIsNone(self.result())

    def test_saved_night_limits_control_quantity_cooldown_and_spread(self):
        limits=Limits(max_contracts=3,overnight_max_contracts=2,overnight_cooldown_minutes=7,overnight_max_spread_ticks=3)
        self.assertEqual(p.quantity(3,self.now,limits=limits),2)
        self.assertEqual(p.cooldown_seconds(300,self.now,limits=limits),420)
        self.assertEqual(p.cooldown_seconds(1200,self.now,limits=limits),1200)
        self.quote['best_ask']=151.75
        self.assertIsNone(p.evaluate(self.signal,self.history,{'CRT','EMA Pullback'},self.bars,self.quote,'micro',self.now,limits=limits))
        self.assertIn('exceeds 2',self.result())

    def test_existing_exposure_blocks_before_data_lookup(self):
        for positions,orders,jobs in [([{}],[],[]),([],[{}],[]),([],[],[dict(alert_id=1,state='Unknown')])]:
            self.assertIn('one position',p.entry_block(self.signal,[],[],positions,orders,jobs,'micro',now=self.now))


class OvernightClaimTests(unittest.TestCase):
    setUp = multi.MultiSymbolTests.setUp
    cycle_mocks = multi.MultiSymbolTests.cycle_mocks

    def test_overnight_claim(self):
        from goxtrade.execution import practice_executor as e
        with patch('goxtrade.strategies.overnight_policy.overnight',return_value=True):
            self.assertFalse(e.claim(job(1,'MNQ',3,'Intent')))
            self.assertTrue(e.claim(job(1,'MNQ',1,'Intent')))
            self.assertFalse(e.claim(job(2,'MES',1,'Intent')))

    def test_cycle_rechecks_filter_and_caps_quantity(self):
        from goxtrade.execution import practice_executor as e
        from datetime import timezone
        self.cycle_mocks([], [dict(id=3,status='Active',symbol='NQ=F',strategy='CRT',signal='LONG',entry=100,stop=95,entry_time=datetime.now(timezone.utc).isoformat())])
        self.stack.enter_context(patch.object(e,'quote_fresh',return_value=True))
        self.stack.enter_context(patch.object(e,'read_status',return_value={}))
        self.stack.enter_context(patch.object(e,'call',return_value=dict(contracts=[dict(id='CON.F.US.MNQ.Z26',symbolId='F.US.MNQ',activeContract=True)])))
        with patch('goxtrade.strategies.overnight_policy.overnight',return_value=True), patch('goxtrade.strategies.overnight_policy.entry_block',return_value=None) as gate, patch.object(e,'post',return_value=dict(success=True,orderId=500)) as api:
            e.cycle('test')
            self.assertEqual(api.call_args.args[1]['size'],1)
            self.assertEqual(gate.call_count,2)

    def test_preflight_deterioration_does_not_submit(self):
        from goxtrade.execution import practice_executor as e
        from datetime import timezone
        self.cycle_mocks([], [dict(id=3,status='Active',symbol='NQ=F',strategy='CRT',signal='LONG',entry=100,stop=95,entry_time=datetime.now(timezone.utc).isoformat())])
        self.stack.enter_context(patch.object(e,'quote_fresh',return_value=True))
        self.stack.enter_context(patch.object(e,'read_status',return_value={}))
        self.stack.enter_context(patch.object(e,'call',return_value=dict(contracts=[dict(id='CON.F.US.MNQ.Z26',symbolId='F.US.MNQ',activeContract=True)])))
        with patch('goxtrade.strategies.overnight_policy.overnight',return_value=True), patch('goxtrade.strategies.overnight_policy.entry_block',side_effect=[None,'Overnight: spread widened']), patch.object(e,'post') as api:
            e.cycle('test')
            api.assert_not_called()
            self.assertIn('spread widened',e.snapshot()[2][0]['error_message'])
