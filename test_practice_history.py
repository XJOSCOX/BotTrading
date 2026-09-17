import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import live_store
import practice_history as history


class PracticeHistoryTests(unittest.TestCase):
    def test_refresh_is_read_only_persistent_and_deduplicated(self):
        fill = dict(id=1, accountId=history.ACCOUNT_ID, creationTimestamp="2026-09-17T03:00:00Z",
                    profitAndLoss=None, fees=1.0)
        responses = [{"success": True, "accounts": [dict(id=history.ACCOUNT_ID, name=history.ACCOUNT_NAME, simulated=True)]},
                     {"success": True, "trades": [fill]},
                     {"success": True, "positions": []}, {"success": True, "orders": []}]
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store, "DB_PATH", Path(folder) / "test.db"):
            with patch.object(history, "post", side_effect=responses * 2) as api:
                history.refresh("test")
                history.refresh("test")
            state, fills = history.snapshot()
            self.assertFalse(state["error"])
            self.assertEqual(len(fills), 1)
            self.assertEqual({c.args[0] for c in api.call_args_list}, {"/api/Account/search", "/api/Trade/search", "/api/Position/searchOpen", "/api/Order/searchOpen"})
            self.assertEqual(api.call_args_list[1].args[1]["accountId"], history.ACCOUNT_ID)
            self.assertEqual(history.totals(fills)["wins"], 0)

    def test_wrong_account_fails_before_trade_fetch(self):
        with patch.object(history, "post", return_value={"success": True, "accounts": []}) as api:
            with self.assertRaises(ValueError):
                history.refresh("test")
            self.assertEqual(api.call_count, 1)

    def test_totals_exclude_voided_and_do_not_count_entry_as_loss(self):
        fills = [dict(profitAndLoss=None, fees=1), dict(profitAndLoss=10, fees=1),
                 dict(profitAndLoss=-5, fees=1), dict(profitAndLoss=100, fees=1, voided=True)]
        self.assertEqual(history.totals(fills), dict(wins=1, losses=1, pnl=5, fees=3))


if __name__ == "__main__":
    unittest.main()
