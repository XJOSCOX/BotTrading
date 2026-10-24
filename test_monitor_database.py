import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
import live_store
import strategy_settings


class DatabaseReadTests(unittest.TestCase):
    def test_existing_connection_does_not_initialize_schema(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store,'DB_PATH',Path(folder)/'test.db'):
            with closing(live_store.connect()) as c:
                self.assertTrue(c.execute("SELECT 1 FROM sqlite_master WHERE name='live_ticks'").fetchone())
            with patch.object(live_store,'init_db',side_effect=AssertionError('schema write on existing reader')):
                with closing(live_store.connect()) as c:
                    self.assertEqual(c.execute('SELECT count(*) FROM latest_quotes').fetchone()[0],0)

    def test_settings_reads_do_not_create_tables(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store,'DB_PATH',Path(folder)/'test.db'):
            self.assertEqual(strategy_settings.read_stop_minutes(),5)
            self.assertEqual(strategy_settings.read_orb_minutes(),15)
            with closing(live_store.connect()) as c:
                self.assertFalse(c.execute("SELECT 1 FROM sqlite_master WHERE name IN ('stop_settings','strategy_settings')").fetchone())
            strategy_settings.save_stop_minutes(10)
            strategy_settings.save_orb_minutes(30)
            self.assertEqual(strategy_settings.read_stop_minutes(),10)
            self.assertEqual(strategy_settings.read_orb_minutes(),30)
