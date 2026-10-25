from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from goxtrade.execution.signal_reservations import initialize, reserve, transition, pending
from tests.manager_fixtures import NOW, candidate, facts, policy


class ReservationTests(unittest.TestCase):
    def test_competing_workers_share_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"manager.db"
            with closing(sqlite3.connect(path)) as conn:
                initialize(conn)
            def worker(number):
                with closing(sqlite3.connect(path, timeout=5)) as conn:
                    return reserve(conn, [candidate(symbol="MNQ" if number == 0 else "MES", key=str(number))], facts(), policy(), NOW)
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(worker, (0, 1)))
            self.assertEqual(sum(d.selected for rows in results for d in rows), 1)
            with closing(sqlite3.connect(path)) as conn:
                self.assertEqual(len(pending(conn, "test", "research")), 1)

    def test_uncertainty_restart_and_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"manager.db"
            with closing(sqlite3.connect(path)) as conn:
                reserve(conn, [candidate()], facts(), policy(), NOW)
                identifier = pending(conn, "test", "research")[0]["id"]
                transition(conn, identifier, "intent", reason="Simulated send intention")
                transition(conn, identifier, "unresolved", reason="Mock submission timeout")
            with closing(sqlite3.connect(path)) as conn:
                result = reserve(conn, [candidate("orb", symbol="MES", key="other")], facts(), policy(max_positions=3, max_group_positions=3), NOW)
                self.assertIn("Unresolved", result[0].reasons[0])
                self.assertFalse(result[0].selected)
                transition(conn, identifier, "partial", reason="Mock fill observed", order_id="paper-fill")
                self.assertFalse(reserve(conn, [candidate("orb", symbol="MES", key="another")], facts(), policy(), NOW)[0].selected)
                transition(conn, identifier, "confirmed", reason="Full paper fill verified", order_id="paper-fill")
                transition(conn, identifier, "closed", reason="Observed flat simulation")
                self.assertFalse(pending(conn, "test", "research"))
                self.assertFalse(reserve(conn, [candidate()], facts(), policy(), NOW)[0].selected)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM manager_reservation_audit").fetchone()[0], 6)

    def test_rejection_never_retries_consumed_intent(self):
        with closing(sqlite3.connect(":memory:")) as conn:
            reserve(conn, [candidate()], facts(), policy(), NOW)
            identifier = pending(conn, "test", "research")[0]["id"]
            transition(conn, identifier, "rejected", reason="Mock rejection")
            self.assertFalse(reserve(conn, [candidate()], facts(), policy(), NOW)[0].selected)
            with self.assertRaises(ValueError):
                transition(conn, identifier, "reserved", reason="Blind retry prohibited")

    def test_broker_reservations_prohibited(self):
        with closing(sqlite3.connect(":memory:")) as conn:
            with self.assertRaises(ValueError):
                reserve(conn, [candidate(profile="leader")], facts(profile="leader"), policy(), NOW)

    def test_database_contention_cannot_authorize(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"manager.db"
            a, b = sqlite3.connect(path), sqlite3.connect(path, timeout=.05)
            try:
                initialize(a)
                a.execute("BEGIN IMMEDIATE")
                with self.assertRaises(sqlite3.OperationalError):
                    reserve(b, [candidate()], facts(), policy(), NOW)
                self.assertEqual(a.execute("SELECT COUNT(*) FROM manager_reservations").fetchone()[0], 0)
            finally:
                a.rollback()
                a.close()
                b.close()
