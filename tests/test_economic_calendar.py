"""Scheduled-news restrictions use fixture events, never broker traffic."""
from contextlib import closing
from datetime import datetime,timezone,timedelta
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch,Mock

import requests
from goxtrade.data import live_store
from goxtrade.market import economic_calendar as cal
from goxtrade.market.trading_schedule import execution_schedule
from tests import test_multi_symbol_entries as multi


class EconomicCalendarTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.patch=patch.object(live_store,'DB_PATH',Path(folder.name)/'test.db')
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.now=datetime(2026,10,28,18,tzinfo=timezone.utc)
        self.policy={**cal.DEFAULTS,'enabled':True}
        self.seed_sources()
        cal.save_settings(self.policy)

    def seed_sources(self):
        with closing(live_store.connect()) as conn:
            cal.init(conn)
            for source in cal.SOURCES:
                conn.execute('INSERT OR REPLACE INTO economic_calendar_sources VALUES(?,?)',(source,json.dumps(dict(updated_at=(self.now-timedelta(hours=1)).isoformat(),attempted_at=(self.now-timedelta(hours=1)).isoformat()))))
            conn.commit()

    def add(self,title='Fixture rate release',impact='critical',at=None):
        return cal.add_event(dict(title=title,event_at=(at or self.now).isoformat(),impact=impact,source_url='https://www.federalreserve.gov/'))

    def test_window_boundaries_and_overlap_use_latest_end(self):
        self.add()
        self.add('Fixture press conference',at=self.now+timedelta(minutes=30))
        self.assertIsNone(cal.entry_block(self.now-timedelta(minutes=30,seconds=1),'practice'))
        self.assertIn('Fixture rate release',cal.entry_block(self.now-timedelta(minutes=30),'practice'))
        self.assertIn('14:30',cal.entry_block(self.now,'practice'))
        self.assertIsNone(cal.entry_block(self.now+timedelta(minutes=90),'practice'))

    def test_leader_disabled_guard_and_unselected_impacts_do_not_restrict(self):
        self.add()
        self.assertIsNone(cal.entry_block(self.now,'leader'))
        cal.save_settings({**self.policy,'enabled':False})
        self.assertIsNone(cal.entry_block(self.now,'practice'))
        cal.save_settings({**self.policy,'impacts':['low']})
        self.assertIsNone(cal.entry_block(self.now,'practice'))

    def test_schedule_blocks_entries_never_flattens_and_replay_does_not_read_live_events(self):
        self.add()
        with patch('goxtrade.market.calendar_guard.restriction',return_value=dict(allow_entry=True,flatten=False)),patch.object(cal,'PROFILE','practice'):
            state=execution_schedule(self.now)
            self.assertFalse(state['allow_entry']); self.assertFalse(state['flatten'])
            self.assertTrue(execution_schedule(self.now,calendar=False)['allow_entry'])

    def test_stale_sources_fail_closed_without_network_and_settings_survive_reads(self):
        self.add()
        with patch.object(cal.requests,'get',side_effect=AssertionError('Entry checks must not fetch')):
            self.assertIn('Fixture',cal.entry_block(self.now,'practice'))
            self.assertIn('stale',cal.entry_block(self.now+timedelta(days=4),'practice'))
        self.assertEqual(cal.settings(),self.policy)

    def test_dst_and_timezone_conversion(self):
        self.assertEqual(cal.chicago_time('2026-10-28T13:00').hour,18)
        self.assertEqual(cal.chicago_time('2026-11-10T07:30').hour,13)
        for value in ('2026-11-01T01:30','2026-03-08T02:30'):
            with self.assertRaises(ValueError):cal.chicago_time(value)
        with self.assertRaises(ValueError):cal.utc('2026-10-28T13:00')

    def test_fed_parser_uses_provider_dates_and_ignores_approximate_times(self):
        payload=dict(events=[dict(title='FOMC Meeting',type='FOMC',month='2026-10',days='28',time='2:00 p.m.'),
                             dict(title='No exact time',type='Other',month='2026-10',days='28',time='Approximate')])
        rows=cal.fed_events(payload,self.now)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['impact'],'critical')
        self.assertEqual(rows[0]['event_at'],'2026-10-28T18:00:00+00:00')

    def test_bea_parser_requires_declared_year(self):
        html='<table id="release-schedule-table"><tr><th>Year 2026</th><th></th><th>Release</th></tr><tr><td><div>October 29</div><small>8:30 AM</small></td><td>News</td><td>GDP (Fixture)</td></tr></table>'
        rows=cal.bea_events(html,self.now)
        self.assertEqual(rows[0]['event_at'],'2026-10-29T12:30:00+00:00')
        self.assertEqual(rows[0]['impact'],'high')
        with self.assertRaises(ValueError):cal.bea_events(html.replace('Year 2026','Unknown'),self.now)

    def test_failed_refresh_retains_reviewed_events_and_last_success(self):
        row=self.add()
        with patch.object(cal.requests,'get',side_effect=requests.ConnectionError('fixture outage')):
            result=cal.refresh(self.now)
        self.assertTrue(any(r['id']==row['id'] for r in result['events']))
        self.assertEqual(result['sources']['fed']['updated_at'],(self.now-timedelta(hours=1)).isoformat())
        self.assertIn('retained',result['sources']['fed']['error'])

    def test_manual_delete_cannot_remove_provider_records(self):
        row=self.add();cal.delete_event(row['id'])
        self.assertEqual(cal.snapshot(self.now)['events'],[])
        with closing(live_store.connect()) as conn:
            conn.execute('INSERT INTO economic_events VALUES(?,?,?,?)',(row['id'],'fed',row['event_at'],json.dumps({**row,'source':'fed'})));conn.commit()
        cal.delete_event(row['id'])
        self.assertEqual(len(cal.snapshot(self.now)['events']),1)

    def test_invalid_configuration_rejected(self):
        for value in ({**self.policy,'before_minutes':-1},{**self.policy,'stale_hours':0},{**self.policy,'impacts':['unknown']}):
            with self.assertRaises(ValueError):cal.save_settings(value)


class EconomicExecutorTests(unittest.TestCase):
    setUp=multi.MultiSymbolTests.setUp
    cycle_mocks=multi.MultiSymbolTests.cycle_mocks

    def test_news_pause_does_not_flatten_or_disable_existing_exit_management(self):
        from goxtrade.execution import practice_executor as executor
        job=multi.job(1,'MNQ',1)
        signal=dict(id=1,status='Active',symbol='NQ=F',strategy='CRT',signal='LONG',entry=100,stop=95)
        self.cycle_mocks([job],[signal])
        with patch('goxtrade.market.trading_schedule.execution_schedule',return_value=dict(allow_entry=False,flatten=False,reason='Economic event: fixture')),patch.object(executor,'call',return_value=dict(success=True)) as api:
            executor.cycle('fixture')
            api.assert_not_called()
            self.assertEqual(executor.snapshot()[2][0]['state'],'Open')
            signal['status']='Closed'
            executor.cycle('fixture')
            api.assert_called_once()
            self.assertEqual(executor.snapshot()[2][0]['state'],'Closing')

    def test_event_start_during_preflight_prevents_transmission(self):
        from goxtrade.execution import practice_executor as executor
        signal=dict(id=3,status='Active',symbol='NQ=F',strategy='CRT',signal='LONG',entry=100,stop=95,entry_time=datetime.now(timezone.utc).isoformat())
        self.cycle_mocks([],[signal])
        self.stack.enter_context(patch.object(executor,'quote_fresh',return_value=True))
        self.stack.enter_context(patch.object(executor,'read_status',return_value={}))
        self.stack.enter_context(patch.object(executor,'call',return_value=dict(contracts=[dict(id='CON.F.US.MNQ.Z26',symbolId='F.US.MNQ',activeContract=True)])))
        with patch('goxtrade.market.trading_schedule.execution_schedule',side_effect=[dict(allow_entry=True,flatten=False,reason='Open'),dict(allow_entry=False,flatten=False,reason='Economic event: fixture')]),patch.object(executor,'post') as broker:
            executor.cycle('fixture')
            broker.assert_not_called()
