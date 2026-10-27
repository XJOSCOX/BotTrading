"""Retries use real temporary SQLite claims and mocked broker transport only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
import json
from threading import Barrier
from unittest.mock import patch
import unittest

import requests

from goxtrade.execution import practice_executor as e
from tests import test_multi_symbol_entries as multi
from tests import test_practice_strategy_testing as managed


class PreflightRetryTests(unittest.TestCase):
    setUp = multi.MultiSymbolTests.setUp
    cycle_mocks = multi.MultiSymbolTests.cycle_mocks

    def candidate(self):
        signal = dict(id=3, status='Active', symbol='NQ=F', strategy='CRT', signal='LONG',
                      entry=100., stop=95., entry_time=datetime.now(timezone.utc).isoformat())
        self.cycle_mocks([], [signal])
        self.stack.enter_context(patch.object(e, 'read_status', return_value={}))
        self.stack.enter_context(patch.object(e, 'call', return_value=dict(contracts=[
            dict(id='CON.F.US.MNQ.Z26', symbolId='F.US.MNQ', activeContract=True)])))
        return signal

    def abort(self):
        self.candidate()
        with patch.object(e, 'quote_fresh', side_effect=[True, False]), patch.object(e, 'post') as transport:
            e.cycle('fixture')
            transport.assert_not_called()
        old = e.snapshot()[2][0]
        self.assertTrue(e.retryable_preflight(old))
        self.assertEqual(old['attempt'], 1)
        return old

    def fresh_job(self, old):
        return {k: v for k, v in old.items() if k not in ('error_message', 'state_updated_at')} | dict(state='Intent')

    def test_abort_then_revalidate_and_send_exactly_once(self):
        self.abort()
        saved_settings = e.snapshot()[0]
        def submit(path, payload, **kwargs):
            self.assertEqual(path, '/api/Order/place')
            self.assertEqual(e.snapshot()[2][0]['submission_status'], 'SENDING')
            return dict(success=True, orderId=1234)
        with patch.object(e, 'quote_fresh', return_value=True), patch.object(e, 'post', side_effect=submit) as transport:
            e.cycle('fixture')
            job = e.snapshot()[2][0]
            self.assertEqual((job['state'], job['attempt'], job['order_id']), ('Submitted', 2, 1234))
            self.assertFalse(e.retryable_preflight(job))
            e.cycle('fixture')
            self.assertEqual(transport.call_count, 1)
        self.assertEqual(saved_settings, e.snapshot()[0])
        with closing(e.db()) as conn:
            states = [json.loads(r[0])['state'] for r in conn.execute(
                'SELECT record FROM practice_job_events WHERE alert_id=3 ORDER BY id')]
        self.assertEqual(states, ['Rejected', 'Intent', 'Submitted'])

    def test_concurrent_retry_claim_has_exactly_one_winner(self):
        old = self.abort()
        barrier = Barrier(2)
        def attempt(_):
            barrier.wait(timeout=5)
            return e.claim(self.fresh_job(old))
        with ThreadPoolExecutor(max_workers=2) as pool:
            winners = list(pool.map(attempt, range(2)))
        self.assertEqual(sorted(winners), [False, True])
        self.assertFalse(e.claim(self.fresh_job(old)))
        self.assertEqual(len(e.snapshot()[2]), 1)

    def test_pause_expiry_and_changed_identity_prevent_retry(self):
        old = self.abort()
        e.pause()
        self.assertFalse(e.claim(self.fresh_job(old)))
        e.update_settings(enabled=True)
        for changed in (dict(contract_id='changed'), dict(side=1), dict(config_fingerprint='changed'),
                        dict(automation_session='different-session')):
            self.assertFalse(e.claim({**self.fresh_job(old), **changed}))
        with patch.object(e.entry_confirmation, 'window_open', return_value=False), \
                patch.object(e, 'quote_fresh', return_value=True), patch.object(e, 'post') as transport:
            e.cycle('fixture')
            transport.assert_not_called()
        self.assertEqual(e.snapshot()[2][0]['state'], 'Rejected')

    def test_retries_still_obey_confirmation_and_new_broker_exposure(self):
        self.abort()
        with patch.object(e.entry_confirmation, 'check', return_value=dict(state='Waiting', reason='Not confirmed')), \
                patch.object(e, 'quote_fresh', return_value=True), patch.object(e, 'post') as transport:
            e.cycle('fixture')
            transport.assert_not_called()
        with patch.object(e, 'account_state', return_value=([dict(contractId='external')], [])), \
                patch.object(e, 'post') as transport:
            e.cycle('fixture')
            transport.assert_not_called()
        self.assertEqual(e.snapshot()[2][0]['attempt'], 1)

    def test_event_consumption_remains_owned_by_the_original_alert(self):
        job = dict(alert_id=3, state='Intent', account_profile='practice', symbol='MNQ', side=0,
                   contract_id='CON.F.US.MNQ.Z26', strategy='CRT', unique_setup_id='original-setup')
        self.assertTrue(e.claim(job))
        job.update(state='Rejected', error_message='Not submitted: fixture preflight')
        e.save_job(job)
        self.assertFalse(e.claim({**self.fresh_job(job), 'alert_id': 4}))
        self.assertTrue(e.claim(self.fresh_job(job)))
        with closing(e.db()) as conn:
            self.assertEqual([tuple(r) for r in conn.execute('SELECT * FROM practice_entry_events')],
                             [('original-setup', 3)])

    def test_inactive_saved_alert_and_other_active_claim_still_block_retry(self):
        old = self.abort()
        with closing(e.db()) as conn:
            conn.execute('CREATE TABLE bot_alert_history(id INTEGER PRIMARY KEY,record TEXT)')
            conn.execute('INSERT INTO bot_alert_history VALUES (3,?)', (json.dumps(dict(status='Closed')),))
            conn.commit()
        self.assertFalse(e.claim(self.fresh_job(old)))
        with closing(e.db()) as conn:
            conn.execute('UPDATE bot_alert_history SET record=?', (json.dumps(dict(status='Active')),))
            conn.commit()
        self.assertTrue(e.claim(dict(alert_id=4, state='Intent', symbol='MNQ',
                                     contract_id='CON.F.US.MNQ.Z26', side=0)))
        self.assertFalse(e.claim(self.fresh_job(old)))

    def test_ambiguous_broker_rejected_filled_and_legacy_records_never_retry(self):
        job = self.abort()
        for changes in (dict(state='Intent'), dict(state='Unknown'), dict(state='Submitted'), dict(state='Closed'),
                        dict(state='Open'), dict(state='Closing'), dict(submission_status='SENDING'),
                        dict(submission_status=None), dict(order_id=123), dict(fill_price=100.),
                        dict(filled_quantity=1), dict(error_code=2), dict(account_id=e.ACCOUNT_ID+1),
                        dict(account_profile='leader')):
            self.assertFalse(e.retryable_preflight({**job, **changes}), changes)
        with patch.object(e, 'PROFILE', 'leader'):
            self.assertFalse(e.retryable_preflight(job))

    def test_timeout_after_transport_boundary_is_never_retried(self):
        self.abort()
        def timeout(*args, **kwargs):
            self.assertEqual(e.snapshot()[2][0]['submission_status'], 'SENDING')
            raise requests.Timeout('Ambiguous broker outcome')
        with patch.object(e, 'quote_fresh', return_value=True), patch.object(e, 'post', side_effect=timeout) as transport:
            with self.assertRaises(requests.Timeout):
                e.cycle('fixture')
            self.assertEqual(e.snapshot()[2][0]['state'], 'Unknown')
            self.assertFalse(e.snapshot()[0]['enabled'])
            e.cycle('fixture')
            self.assertEqual(transport.call_count, 1)


    def test_actual_broker_rejection_remains_non_retryable_after_manual_resume(self):
        self.abort()
        with patch.object(e, 'quote_fresh', return_value=True), \
                patch.object(e, 'post', return_value=dict(success=False, errorCode=2)) as transport:
            e.cycle('fixture')
            self.assertFalse(e.retryable_preflight(e.snapshot()[2][0]))
            e.update_settings(enabled=True)
            e.cycle('fixture')
            self.assertEqual(transport.call_count, 1)


class ManagedPreflightRetryTests(unittest.TestCase):
    setUp = multi.MultiSymbolTests.setUp
    cycle_mocks = multi.MultiSymbolTests.cycle_mocks
    prepare = managed.PracticeStrategyCycleTests.prepare

    def test_real_manager_reselects_same_event_and_preserves_saved_session(self):
        transport = self.prepare()
        before = e.snapshot()[0]
        with patch.object(e, 'quote_fresh', side_effect=[True, False]):
            e.cycle('fixture')
        transport.assert_not_called()
        self.assertTrue(e.retryable_preflight(e.snapshot()[2][0]))
        e.cycle('fixture')
        self.assertEqual(transport.call_count, 1)
        self.assertEqual(e.snapshot()[2][0]['attempt'], 2)
        self.assertEqual(e.snapshot()[0], before)
        e.cycle('fixture')
        self.assertEqual(transport.call_count, 1)

    def test_manager_risk_change_still_blocks_previously_unsent_signal(self):
        transport = self.prepare()
        with patch.object(e, 'quote_fresh', side_effect=[True, False]):
            e.cycle('fixture')
        settings = e.snapshot()[0]
        session = settings['strategy_testing']
        changed = {**session, 'policy': {**session['policy'], 'max_trade_risk': 0.01}}
        e.update_settings(strategy_testing=changed)
        e.cycle('fixture')
        transport.assert_not_called()
        self.assertEqual(e.snapshot()[2][0]['attempt'], 1)

