import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from goxtrade.execution import live_accounts


class LiveAccountsTests(unittest.TestCase):
    def test_only_enabled_accounts_and_leader_first(self):
        accounts = [
            dict(id=1, name="disabled", canTrade=False),
            dict(id=2, name="unknown"),
            dict(id=3, name="TEST_FOLLOWER", canTrade=True),
            dict(id=4, name="TEST_LEADER", canTrade=True),
        ]
        from goxtrade.config import execution_identity
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(live_accounts,"COPY_PROFILE",Path(folder)/"copy.json"), \
                patch.object(execution_identity,"ACCOUNT_FILE",Path(folder)/"missing-identity.json"):
            live_accounts.COPY_PROFILE.write_text('{"leader":"TEST_LEADER","followers":["TEST_FOLLOWER"]}',encoding="utf-8")
            self.assertEqual([a["id"] for a in live_accounts.enabled_accounts(accounts)], [4,3])
            self.assertEqual(live_accounts.copy_role(accounts[2]), "Follower")

    def test_discovery_includes_inactive_and_no_orders(self):
        with patch.object(live_accounts, "post", return_value={"success": True, "accounts": [{"id": 1, "canTrade": False}]}) as post:
            self.assertEqual(len(live_accounts.search_accounts()), 1)
            post.assert_called_once_with("/api/Account/search", {"onlyActiveAccounts": False})

    def test_defaults_limits_and_persistence(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live_accounts, "SETTINGS", Path(folder)/"settings.json"):
            self.assertEqual(live_accounts.quantities_for(1), dict(MNQ=2,MES=2,MYM=2))
            live_accounts.save_quantities(1, dict(MNQ=1,MES=3,MYM=4))
            self.assertEqual(live_accounts.quantities_for(1), dict(MNQ=1,MES=3,MYM=4))
            self.assertEqual(live_accounts.quantities_for(2), dict(MNQ=2,MES=2,MYM=2))
            for value in (0,5,2.5,True):
                with self.assertRaises(ValueError):
                    live_accounts.save_quantities(1,dict(MNQ=value,MES=2,MYM=2))

    def test_account_page_refresh_is_explicit_and_read_only(self):
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as folder, patch('goxtrade.data.live_store.DB_PATH', Path(folder)/"test.db"), \
                patch('goxtrade.execution.practice_history.ensure_worker'), patch('goxtrade.ui.accounts.credentials_present', return_value=True), \
                patch('goxtrade.ui.accounts.search_accounts', return_value=[dict(id=123,name="Test",balance=50000,canTrade=True,simulated=True)]) as search:
            app = AppTest.from_file("app.py")
            app.query_params["page"] = "Accounts"
            app.run(timeout=20)
            self.assertFalse(app.exception)
            search.assert_not_called()
            next(button for button in app.button if button.label == "Refresh accounts").click().run()
            self.assertFalse(app.exception)
            search.assert_called_once()
            self.assertEqual(app.dataframe[0].value.iloc[0]["ID"], 123)


if __name__ == "__main__":
    unittest.main()
