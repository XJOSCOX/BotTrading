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
                patch("goxtrade.execution.projectx_client.post", side_effect=AssertionError("Broker calls forbidden")) as broker:
            app = AppTest.from_string("from goxtrade.ui.bot.vwap_ema_panel import render\nrender()")
            app.run(timeout=30)
            self.assertEqual(len(app.exception), 0, [value.message for value in app.exception])
            self.assertIn("Parameters", [tab.label for tab in app.tabs])
            self.assertIn("Backtest", [tab.label for tab in app.tabs])
            self.assertFalse(app.checkbox(key="vwap_setting_practice_enabled").value)
            self.assertFalse(app.checkbox(key="vwap_setting_paper_enabled").value)
            # Saving parameters cannot arm an account.
            next(button for button in app.button if button.label == "Save VWAP settings").click().run(timeout=30)
            self.assertEqual(len(app.exception), 0, [value.message for value in app.exception])
            self.assertFalse(read_vwap_ema_config().practice_enabled)
            broker.assert_not_called()

    def test_research_requires_entered_fees_or_explicit_zero_scenario(self):
        import datetime
        from tests.test_strategy_backtesting import long_fixture
        from goxtrade.research.result_store import saved_runs
        source = long_fixture()
        source["complete"] = True
        with tempfile.TemporaryDirectory() as directory, patch.object(live_store, "DB_PATH", Path(directory)/"research.db"), \
                patch("goxtrade.data.strategy_history.load_strategy_minutes", return_value=source), \
                patch("goxtrade.execution.projectx_client.post", side_effect=AssertionError("Broker calls forbidden")) as broker:
            app = AppTest.from_string("from goxtrade.ui.bot.strategy_research import render_research\nfrom goxtrade.strategies.vwap_ema_config import VwapEmaConfig\nrender_research(VwapEmaConfig(stop_method='fixed',management_method='fixed'))")
            app.run(timeout=30)
            app.selectbox(key="research_source").select("Saved contract history")
            app.text_input(key="research_contract").set_value("TEST.CONTRACT")
            app.date_input(key="research_start").set_value(datetime.date(2026, 10, 1))
            app.date_input(key="research_end").set_value(datetime.date(2026, 10, 2))
            app.button(key="run_strategy_research").click().run(timeout=30)
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("commission" in error.value.lower() for error in app.error))
            self.assertEqual(saved_runs(), [])
            app.checkbox(key="research_zero_cost").check()
            app.button(key="run_strategy_research").click().run(timeout=30)
            self.assertEqual(len(app.exception), 0, [value.message for value in app.exception])
            self.assertEqual(len(saved_runs()), 1)
            self.assertTrue(saved_runs()[0]["result"]["simulation"]["zero_cost_sensitivity"])
            broker.assert_not_called()
