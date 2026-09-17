import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import live_store
import practice_safety as s


class SafetyTests(unittest.TestCase):
    def test_lock_latches_until_explicit_acknowledgement(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store,"DB_PATH",Path(folder)/"test.db"):
            self.assertFalse(s.check(10000)["locked"])
            self.assertFalse(s.check(9500.01)["locked"])
            self.assertTrue(s.check(9500)["locked"])
            self.assertTrue(s.check(11000, fallback=11000)["locked"])
            self.assertTrue(s.snapshot()["locked"])
            self.assertFalse(s.check(11000, acknowledge=True)["locked"])
            self.assertEqual(s.snapshot()["baseline"],11000)
            self.assertTrue(s.check(10500)["locked"])
