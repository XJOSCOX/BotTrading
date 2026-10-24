import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd

from goxtrade.bot import bot_monitor
from goxtrade.data import live_store


class MonitorTests(unittest.TestCase):
    def test_each_pair_uses_price_received_after_history_load(self):
        old = pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=3)
        history = pd.DataFrame({"id": [1], "time": [old], "price": [100.0]})
        latest = pd.DataFrame({"id": [2], "time": [pd.Timestamp.now(tz="UTC")], "price": [101.0]})
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store, "DB_PATH", Path(folder)/"test.db"), patch.object(bot_monitor, "alert_history", return_value=[]), patch.object(bot_monitor, "chart_history", return_value=pd.DataFrame()), patch.object(bot_monitor, "price_history_for_symbol", return_value=history), patch.object(bot_monitor, "ticks_for_symbol", return_value=latest), patch.object(bot_monitor, "evaluate_strategy_status", return_value={"signal": {"signal": "WAIT"}}) as evaluate:
            bot_monitor.monitor_once()
            self.assertEqual(evaluate.call_count, 15)
            for call in evaluate.call_args_list:
                self.assertEqual(call.args[3].iloc[-1]["price"], 101.0)
            self.assertTrue(all(r["feed_fresh"] for r in bot_monitor.read_status().values()))

    def test_fifteen_pairs_without_ui_and_legacy_exit_only(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store, "DB_PATH", Path(folder) / "test.db"):
            data = pd.DataFrame({"time": [pd.Timestamp.now(tz="UTC")]})
            def evaluate(symbol, strategy, session, ticks, allow_new=True, **kwargs):
                return {"signal": {"signal": "WAIT"}, "candles": data}
            with patch.object(bot_monitor,"chart_history",return_value=data), patch.object(bot_monitor, "price_history_for_symbol", return_value=data) as history, patch.object(
                bot_monitor, "evaluate_strategy_status", side_effect=evaluate
            ) as evaluate_mock, patch.object(bot_monitor, "alert_history", return_value=[
                {"symbol": "MNQ=F", "strategy": "CRT", "status": "Active"}
            ]):
                bot_monitor.monitor_once()
                self.assertEqual(history.call_count, 4)
                self.assertEqual(evaluate_mock.call_count, 16)
                for call in evaluate_mock.call_args_list:
                    self.assertEqual(call.kwargs["allow_new"], call.args[0] in bot_monitor.SYMBOLS)
            records = bot_monitor.read_status()
            for symbol in bot_monitor.SYMBOLS:
                for strategy in bot_monitor.STRATEGIES:
                    record = records[symbol, strategy]
                    self.assertTrue(record["feed_fresh"])
                    self.assertNotIn("candles", record)
                    self.assertIn("updated_at", record)

    def test_session_clock_is_read_after_history(self):
        events = []
        original = bot_monitor.market_session
        def clock():
            events.append("clock")
            return original()
        def history(*args, **kwargs):
            events.append("history")
            return pd.DataFrame({"time":[pd.Timestamp.now(tz="UTC")]})
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store,"DB_PATH",Path(folder)/"test.db"), patch.object(bot_monitor,"market_session",side_effect=clock), patch.object(bot_monitor,"price_history_for_symbol",side_effect=history), patch.object(bot_monitor,"chart_history",return_value=pd.DataFrame()), patch.object(bot_monitor,"alert_history",return_value=[]), patch.object(bot_monitor,"evaluate_strategy_status",return_value={"signal":{"signal":"WAIT"}}):
            bot_monitor.monitor_once()
        self.assertEqual(events[:3],["history"]*3)
        self.assertEqual(events.count("clock"),15)


if __name__ == "__main__":
    unittest.main()
