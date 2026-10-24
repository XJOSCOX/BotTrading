import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import live_store
import run_live_market


class FeedStartupTests(unittest.TestCase):
    def test_failed_initial_contract_refresh_is_retried(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store, "DB_PATH", Path(folder) / "test.db"), patch.object(
            run_live_market, "Thread"
        ), patch.object(run_live_market, "load_symbols", return_value=[]), patch.object(
            run_live_market, "refresh_active_contracts", side_effect=[RuntimeError("auth unavailable"), None]
        ) as refresh, patch.object(
            run_live_market, "symbols_with_contracts", return_value=[{"contract_id": "test"}]
        ), patch.object(run_live_market, "run_connection") as connect, patch.object(
            run_live_market.time, "sleep", side_effect=[None, StopIteration]
        ):
            with self.assertRaises(StopIteration):
                run_live_market.main()
        self.assertEqual(refresh.call_count, 2)
        connect.assert_called_once()


if __name__ == "__main__":
    unittest.main()
