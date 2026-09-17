from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import live_store
import bot_view


class BotPriceTests(unittest.TestCase):
    def test_summary_uses_closed_direction_adjusted_outcomes(self):
        rows = [
            dict(status="Closed", signal="LONG", entry=100, exit_price=110),
            dict(status="Closed", signal="SHORT", entry=100, exit_price=90),
            dict(status="Closed", signal="SHORT", entry=100, exit_price=105),
            dict(status="Closed", signal="LONG", entry=100, exit_price=100),
            dict(status="Closed", signal="LONG", entry=100, exit_price=None),
            dict(status="Active", signal="LONG", entry=100, exit_price=120),
        ]
        self.assertEqual(bot_view.alert_outcomes(rows), dict(wins=2, losses=1, breakeven=1, unknown=1, win_rate=50))
        self.assertIsNone(bot_view.alert_outcomes([])["win_rate"])

    def test_latest_priced_event_per_symbol(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store, "DB_PATH", Path(folder) / "test.db"):
            with closing(live_store.connect()) as conn:
                for symbol, value in (("NQ=F", 100), ("ES=F", 200), ("NQ=F", 101), ("NQ=F", None)):
                    conn.execute("INSERT INTO live_ticks (symbol,contract_id,event_type,price,received_at) VALUES (?, 'test', 'trade', ?, ?)", (symbol, value, live_store.utc_now()))
                conn.commit()
            prices = live_store.latest_prices(["NQ=F", "ES=F", "YM=F"])
            self.assertEqual(prices["NQ=F"]["price"], 101)
            self.assertEqual(prices["ES=F"]["price"], 200)
            self.assertNotIn("YM=F", prices)

    def test_evidence_visible_and_closed_result_frozen(self):
        row = dict(id=1, signal="LONG", status="Closed", entry=100, exit_price=110,
                   stop=95, target=110, symbol="NQ=F", strategy="CRT", trigger_detail="<evidence>")
        with patch.object(bot_view.st, "html") as html:
            bot_view.history_card(row, dict(price=80, received_at=live_store.utc_now()))
            markup = html.call_args.args[0]
            self.assertIn("+10.00 pts", markup)
            self.assertIn("&lt;evidence&gt;", markup)
            self.assertNotIn("<details", markup)
            self.assertNotIn("pts from entry", markup)

    def test_feed_status(self):
        self.assertEqual(bot_view.feed_status(None, True), "No data")
        self.assertEqual(bot_view.feed_status(dict(received_at=live_store.utc_now()), True), "Live")
        self.assertEqual(bot_view.feed_status(dict(received_at="2000-01-01T00:00:00Z"), True), "Delayed")
        self.assertEqual(bot_view.feed_status(dict(received_at=live_store.utc_now()), False), "Market closed")


if __name__ == "__main__":
    unittest.main()
