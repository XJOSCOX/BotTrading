from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from goxtrade.bot import bot_controls, strategy_events
from goxtrade.bot.signal_lifecycle import track_signal, alert_history
from goxtrade.bot.watch_alerts import clear_watch_alerts
from goxtrade.data import live_store
from goxtrade.data.strategy_history import load_strategy_minutes
from goxtrade.execution import practice_executor
from goxtrade.strategies.strategy_catalog import execution_block
from goxtrade.strategies.strategy_settings import read_vwap_ema_config, save_vwap_ema_config
from goxtrade.strategies.vwap_ema_config import VwapEmaConfig
from goxtrade.strategies.vwap_ema_cross import evaluate_vwap_ema_cross
from tests.vwap_fixtures import minutes


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.patch = patch.object(live_store, "DB_PATH", Path(temporary.name)/"test.db")
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def candidate(self):
        source = minutes()
        now = source.iloc[-1]["time"]+pd.Timedelta(minutes=1)
        signal = evaluate_vwap_ema_cross(source, 103., now, VwapEmaConfig(stop_method="fixed"), historical=True)[0]
        signal["symbol"] = "NQ=F"
        return signal

    def test_settings_persist_without_enabling_accounts(self):
        before = bot_controls.read()
        self.assertFalse(read_vwap_ema_config().practice_enabled)
        config = save_vwap_ema_config(dict(entry_mode="REALTIME", stop_method="fixed"))
        self.assertEqual(read_vwap_ema_config(), config)
        self.assertEqual(bot_controls.read(), before)
        self.assertFalse(practice_executor.snapshot()[0].get("enabled", False))
        with self.assertRaises(ValueError):
            save_vwap_ema_config(dict(reward_risk=-1))
        self.assertEqual(read_vwap_ema_config(), config)

    def test_leader_is_blocked_even_with_explicit_practice_permission(self):
        save_vwap_ema_config(replace(VwapEmaConfig(), practice_enabled=True))
        signal = self.candidate()
        self.assertIsNone(execution_block(signal, "practice"))
        self.assertIn("disabled", execution_block(signal, "leader"))
        with patch.object(practice_executor, "PROFILE", "leader"), patch.object(practice_executor, "post") as post:
            self.assertFalse(practice_executor.claim(dict(strategy="VWAP EMA Cross", entry_mode="CONFIRMED")))
            with self.assertRaises(ValueError):
                practice_executor.build_order(signal, {}, 1)
            post.assert_not_called()
        with self.assertRaises(ValueError):
            bot_controls.save(["MNQ"], ["VWAP EMA Cross"], 5, profile="leader")

    def test_disabled_symbol_cannot_claim_by_using_micro_alias(self):
        save_vwap_ema_config(dict(practice_enabled=True, enabled_symbols=["ES=F"]))
        self.assertIn("disabled", execution_block(dict(strategy_id="vwap_ema_cross", entry_mode="CONFIRMED", symbol="MNQ"), "practice"))
        self.assertIsNone(execution_block(dict(strategy_id="vwap_ema_cross", entry_mode="CONFIRMED", symbol="MES"), "practice"))

    def test_event_is_immutable_and_only_consumed_once_after_clear_or_restart(self):
        signal = self.candidate()
        live_store.save_trade("NQ=F", "TEST.CONTRACT", dict(price=103., volume=1., timestamp=signal["detected_at"]))
        original = strategy_events.persist("test", {}, {"sequence": 1}, signal)
        changed = strategy_events.persist("test", {"sequence": 1}, {"sequence": 2}, {**signal, "entry": 104.})
        self.assertEqual(changed["entry"], original["entry"])
        track_signal("NQ=F", "VWAP EMA Cross", signal, signal["unique_setup_id"], True)
        self.assertEqual(len(alert_history()), 1)
        self.assertEqual(clear_watch_alerts([alert_history()[0]["id"]]), 1)
        track_signal("NQ=F", "VWAP EMA Cross", signal, signal["unique_setup_id"], True)
        self.assertEqual(len(alert_history()), 1)
        self.assertEqual(alert_history()[0]["status"], "Dismissed")

    def test_trade_volume_is_incremental_and_never_sums_quote_volume(self):
        now = pd.Timestamp.now(tz="UTC").floor("min")
        contract = "TEST.CONTRACT"
        live_store.save_quote("NQ=F", contract, dict(lastPrice=999., volume=100000., timestamp=now.isoformat()))
        live_store.save_trade("NQ=F", contract, dict(price=100., volume=2., timestamp=now.isoformat()))
        live_store.save_trade("NQ=F", contract, dict(price=100.25, volume=3., timestamp=(now+pd.Timedelta(seconds=1)).isoformat()))
        first = load_strategy_minutes("NQ=F", contract, now+pd.Timedelta(minutes=1))
        second = load_strategy_minutes("NQ=F", contract, now+pd.Timedelta(minutes=1))
        self.assertEqual(first.iloc[-1]["volume"], 5.)
        self.assertEqual(second.iloc[-1]["volume"], 5.)
        self.assertEqual(first.iloc[-1]["high"], 100.25)
        self.assertEqual(first.iloc[-1]["open"], 100.)
        with closing(live_store.connect()) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM live_ticks").fetchone()[0], 3)

    def test_new_settings_do_not_change_active_risk_snapshot(self):
        signal = self.candidate()
        live_store.save_trade("NQ=F", "TEST.CONTRACT", dict(price=103., volume=1., timestamp=signal["detected_at"]))
        track_signal("NQ=F", "VWAP EMA Cross", signal, signal["unique_setup_id"], True)
        save_vwap_ema_config(dict(fixed_stop_ticks=100, reward_risk=3.))
        current = track_signal("NQ=F", "VWAP EMA Cross", {**signal, "stop": 10.}, "different", True)
        self.assertEqual(current["stop"], signal["stop"])
        self.assertEqual(VwapEmaConfig.from_dict(current["config_snapshot"]), VwapEmaConfig.from_dict(signal["config_snapshot"]))
