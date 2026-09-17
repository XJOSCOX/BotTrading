import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import live_accounts


class LiveAccountsTests(unittest.TestCase):
    def test_only_enabled_accounts_and_leader_first(self):
        accounts = [
            dict(id=1, name="disabled", canTrade=False),
            dict(id=2, name="unknown"),
            dict(id=3, name="TEST_FOLLOWER", canTrade=True),
            dict(id=4, name="TEST_LEADER", canTrade=True),
        ]
        with patch.object(Path,"read_text",return_value='{"leader":"TEST_LEADER","followers":["TEST_FOLLOWER"]}'):
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

    def test_page_defaults_and_save(self):
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as folder, patch("practice_history.ensure_worker"), patch.object(live_accounts, "SETTINGS", Path(folder)/"settings.json"), patch("live_page.credentials_present", return_value=True), patch(
            "live_page.search_accounts", return_value=[dict(id=123,name="Test",balance=50000,canTrade=True,simulated=True)]
        ):
            app = AppTest.from_file("app.py")
            app.query_params["page"] = "Live"
            app.run(timeout=20)
            self.assertFalse(app.exception)
            app.selectbox(key="live_account_choice").select(123).run()
            self.assertEqual([app.number_input(key=f"live_qty_123_{s}").value for s in ("MNQ","MES","MYM")], [2,2,2])
            app.number_input(key="live_qty_123_MNQ").set_value(4)
            next(b for b in app.button if b.label == "Save sizing").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(live_accounts.quantities_for(123)["MNQ"],4)


if __name__ == "__main__":
    unittest.main()
