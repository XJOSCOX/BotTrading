from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from goxtrade.data import live_store
from goxtrade.strategies.strategy_settings import read_vwap_ema_config


class StrategyUiTests(unittest.TestCase):
    def test_strategy_workspace_loads_without_credentials_or_broker(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(live_store, "DB_PATH", Path(directory)/"ui.db"), \
                patch("goxtrade.execution.projectx_client.post", side_effect=AssertionError("Broker calls forbidden")):
            app = AppTest.from_string("from goxtrade.ui.bot.vwap_ema_panel import render\nrender()")
            app.run(timeout=30)
            self.assertEqual(len(app.exception), 0, [value.message for value in app.exception])
            self.assertIn("Parameters", [tab.label for tab in app.tabs])
            self.assertIn("Backtest", [tab.label for tab in app.tabs])
            self.assertFalse(app.checkbox(key="vwap_setting_practice_enabled").value)
            self.assertFalse(app.checkbox(key="vwap_setting_paper_enabled").value)
            # Saving parameters cannot arm an account.
            app.button[0].click().run(timeout=30)
            self.assertEqual(len(app.exception), 0, [value.message for value in app.exception])
            self.assertFalse(read_vwap_ema_config().practice_enabled)
