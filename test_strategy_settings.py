import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import live_store
import bot_controls
import strategy_settings
from strategy_catalog import STRATEGIES


class StrategySettingsTests(unittest.TestCase):
    def test_stop_timeframe_defaults_and_validation(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store,"DB_PATH",Path(folder)/"test.db"):
            self.assertEqual(strategy_settings.read_stop_minutes(),5)
            for minutes in (5,10,15):
                strategy_settings.save_stop_minutes(minutes)
                self.assertEqual(strategy_settings.read_stop_minutes(),minutes)
            for minutes in (1,30,True,"5"):
                with self.assertRaises(ValueError):
                    strategy_settings.save_stop_minutes(minutes)

    def test_new_strategies_require_explicit_account_selection(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store,"DB_PATH",Path(folder)/"test.db"):
            self.assertEqual(bot_controls.read("leader")["strategies"],["CRT","Reversal"])
            bot_controls.save(["MNQ","MES"],list(STRATEGIES),5,profile="leader")
            self.assertEqual(bot_controls.read("leader")["strategies"],list(STRATEGIES))
            self.assertEqual(bot_controls.read("practice")["strategies"],["CRT","Reversal"])

    def test_shared_orb_window_validation_and_persistence(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store,"DB_PATH",Path(folder)/"test.db"):
            self.assertEqual(strategy_settings.read_orb_minutes(),15)
            for minutes in (5,15,30):
                strategy_settings.save_orb_minutes(minutes)
                self.assertEqual(strategy_settings.read_orb_minutes(),minutes)
            for minutes in (1,4,60,True,"15"):
                with self.assertRaises(ValueError):
                    strategy_settings.save_orb_minutes(minutes)
            self.assertEqual(strategy_settings.read_orb_minutes(),30)
