from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from goxtrade.data import live_store
from goxtrade.execution import practice_executor as e
from goxtrade.strategies.strategy_catalog import execution_block, order_block
from goxtrade.strategies.strategy_settings import save_vwap_ema_config
from goxtrade.strategies.vwap_ema_config import VwapEmaConfig
from goxtrade.strategies.vwap_ema_cross import evaluate_vwap_ema_cross
from tests.vwap_fixtures import minutes
from tests import test_multi_symbol_entries as multi


class EnvelopeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        p = patch.object(live_store, "DB_PATH", Path(folder.name)/"test.db")
        p.start()
        self.addCleanup(p.stop)
        self.config = save_vwap_ema_config(VwapEmaConfig(practice_enabled=True, stop_method="fixed"))
        source = minutes()
        self.signal = evaluate_vwap_ema_cross(source, 103., source.iloc[-1]["time"]+pd.Timedelta(minutes=1),
                                              self.config, historical=True)[0]
        self.signal.update(symbol="NQ=F", strategy="VWAP EMA Cross")

    def test_conflicting_identity_cannot_hide_indicator_from_leader(self):
        for values in (dict(strategy_id="crt"), dict(strategy="CRT"),
                       dict(strategy_id=None, strategy=None), dict(strategy_id="crt", strategy="CRT")):
            with self.subTest(values=values):
                self.assertIsNotNone(execution_block({**self.signal, **values}, "leader"))

    def test_stripped_metadata_and_wrong_timeframes_fail_closed(self):
        for signal in (dict(entry_policy="indicator-event-v1"), dict(entry_mode="REALTIME"),
                       dict(raw_signal="ANTICIPATED_LONG"), dict(ema=100., vwap=99.), dict(signal_minutes=3),
                       dict(strategy="CRT", signal_minutes=3)):
            self.assertIsNotNone(execution_block(signal, "leader"), signal)
        self.assertIsNone(execution_block(dict(strategy="CRT", signal_minutes=15), "leader"))
        self.assertIsNone(execution_block(dict(entry=100., stop=95.), "practice"))  # Legacy formatting helper, not submission.

    def test_frozen_configuration_and_mode_cannot_be_misrepresented(self):
        self.assertIsNone(execution_block(self.signal, "practice"))
        for field, value in (("config_fingerprint", "wrong"), ("entry_policy", None), ("unique_setup_id", "x"),
                             ("signal_minutes", 15), ("entry_mode", "REALTIME"), ("config_snapshot", None)):
            with self.subTest(field=field):
                self.assertIsNotNone(execution_block({**self.signal, field: value}, "practice"))

    def make_job(self, alert_id=1):
        return dict(**{key: self.signal[key] for key in ("strategy_id", "strategy", "config_snapshot", "config_fingerprint",
                     "entry_policy", "entry_mode", "signal_minutes", "unique_setup_id", "crossover_key", "source_contract", "session_id", "candle_time", "direction")}, alert_id=alert_id,
                    reference_symbol="NQ=F",
                    symbol="MNQ", contract_id="CON.F.US.MNQ.Z26", quantity=1, state="Intent", side=0)

    def test_durable_event_claim_prevents_second_order_even_after_rejection(self):
        with patch("goxtrade.market.calendar_guard.entry_block", return_value=None), patch.object(e.overnight_policy, "overnight", return_value=False):
            first = self.make_job()
            self.assertTrue(e.claim(first))
            first["state"] = "Rejected"
            e.save_job(first)
            self.assertFalse(e.claim(self.make_job(2)))

    def test_mode_change_cannot_trade_consumed_crossover_again(self):
        from goxtrade.strategies.strategy_catalog import crossover_key
        with patch("goxtrade.market.calendar_guard.entry_block", return_value=None), patch.object(e.overnight_policy, "overnight", return_value=False):
            first = self.make_job()
            self.assertTrue(e.claim(first))
            first["state"] = "Rejected"
            e.save_job(first)
            config = replace(self.config, entry_mode="REALTIME")
            save_vwap_ema_config(config)
            changed = self.make_job(2)
            changed.update(entry_mode="REALTIME", config_snapshot=config.to_dict(), config_fingerprint=config.fingerprint, unique_setup_id="a"*64)
            self.assertEqual(changed["crossover_key"], crossover_key(changed))
            self.assertFalse(e.claim(changed))

    def test_reference_contract_rollover_blocks_micro_payload(self):
        signal = dict(self.signal, id=1, source_contract="CON.F.US.ENQ.H27")
        from goxtrade.strategies.strategy_catalog import crossover_key
        signal["crossover_key"] = crossover_key(signal)
        with patch("goxtrade.market.calendar_guard.entry_block", return_value=None):
            with self.assertRaisesRegex(ValueError, "expiries"):
                e.build_order(signal, dict(id="CON.F.US.MNQ.Z26", symbolId="F.US.MNQ", activeContract=True), 1)

    def test_saved_alert_identity_is_checked_even_if_job_metadata_is_stripped(self):
        import json
        with closing(live_store.connect()) as conn:
            conn.execute("CREATE TABLE bot_alert_history (id INTEGER PRIMARY KEY,record TEXT)")
            conn.execute("INSERT INTO bot_alert_history VALUES (1,?)", (json.dumps({**self.signal, "status": "Active"}),))
            conn.commit()
        with patch.object(e, "PROFILE", "leader"), patch.object(e, "post") as post:
            self.assertFalse(e.claim(dict(alert_id=1, state="Intent")))
            post.assert_not_called()

    def test_each_account_requires_permission_and_reviewed_calendar(self):
        with tempfile.TemporaryDirectory() as folder, patch("goxtrade.market.calendar_guard.CALENDAR_PATH", Path(folder)/"absent.json"):
            self.assertIn("calendar", order_block(self.signal, "practice"))
        self.assertIn("explicitly enabled", order_block(self.signal, "leader"))


class SubmissionRaceTests(unittest.TestCase):
    setUp = multi.MultiSymbolTests.setUp
    cycle_mocks = multi.MultiSymbolTests.cycle_mocks

    def setup_candidate(self):
        signal = dict(id=3, status="Active", symbol="NQ=F", strategy="CRT", signal="LONG", entry=100., stop=95.,
                      entry_time=datetime.now(timezone.utc).isoformat())
        self.cycle_mocks([], [signal])
        self.stack.enter_context(patch.object(e, "quote_fresh", return_value=True))
        self.stack.enter_context(patch.object(e, "read_status", return_value={}))
        self.stack.enter_context(patch.object(e, "call", return_value=dict(contracts=[dict(id="CON.F.US.MNQ.Z26", symbolId="F.US.MNQ", activeContract=True)])))
        return signal

    def test_account_loss_change_during_preflight_prevents_submission(self):
        self.setup_candidate()
        e.update_settings(start_balance=50000.)
        with patch.object(e, "verify_account", side_effect=[dict(balance=50000.), dict(balance=49499.)]), patch.object(e, "post") as post:
            e.cycle("mock")
            post.assert_not_called()
        self.assertFalse(e.snapshot()[0]["enabled"])
        self.assertIn("loss lock", e.snapshot()[2][0]["error_message"])

    def test_pause_during_final_confirmation_prevents_submission(self):
        self.setup_candidate()
        calls = []
        def confirmation(signal):
            calls.append(1)
            if len(calls) == 2:
                e.pause()
            return dict(state="Confirmed", reason="mock", price=100.)
        with patch.object(e.entry_confirmation, "check", side_effect=confirmation), patch.object(e, "post") as post:
            e.cycle("mock")
            post.assert_not_called()
        self.assertIn("send boundary", e.snapshot()[2][0]["error_message"])

    def test_new_conflicting_signal_during_preflight_prevents_submission(self):
        signal = self.setup_candidate()
        opposite = dict(signal, id=4, signal="SHORT", strategy="Reversal")
        with patch.object(e, "alert_history", side_effect=[[signal], [signal], [signal, opposite]]), patch.object(e, "post") as post:
            e.cycle("mock")
            post.assert_not_called()
        self.assertIn("conflicting", e.snapshot()[2][0]["error_message"])
