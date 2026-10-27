"""Operational probes use fixtures only; external access is never a unit test."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import tempfile
import sqlite3
import unittest
from unittest.mock import Mock, patch

from goxtrade.data import live_store
from goxtrade.diagnostics import projectx_diagnostics as diagnostics
from goxtrade.diagnostics import operational_evidence as evidence
from tests import test_projectx_diagnostics as fixtures
from tests import test_offline_replay as replay_fixtures


class DiagnosticAcceptanceTests(unittest.TestCase):
    setUp = fixtures.DiagnosticsTests.setUp
    probe = fixtures.DiagnosticsTests.probe

    def test_missing_credentials_invalidate_previous_authentication(self):
        self.probe(Mock(return_value=fixtures.response(success=True, token="SECRET-TOKEN")))
        with patch.dict("os.environ", TOPSTEP_USERNAME="", TOPSTEP_API_KEY=""):
            result = self.probe(Mock(side_effect=AssertionError("No authentication without credentials")))
            self.assertEqual(result["code"], "CONFIG_INVALID")
            self.assertFalse(diagnostics._auth)

    def test_blank_token_is_malformed_not_authenticated(self):
        report = self.probe(Mock(return_value=fixtures.response(success=True, token="  ")))
        self.assertEqual(report["code"], "MALFORMED_RESPONSE")
        self.assertFalse(diagnostics._auth)

    def test_future_market_timestamp_is_not_fresh(self):
        with closing(live_store.connect()) as conn:
            conn.execute("INSERT INTO live_ticks(symbol,contract_id,event_type,price,event_time,received_at) VALUES ('MNQ=F','fixture','trade',100,'2026-10-22T16:00:00Z','2026-10-22T15:00:00Z')")
            conn.commit()
        report = diagnostics.passive("2026-10-22T15:00:00Z")
        self.assertIn("MALFORMED_RESPONSE", report["market_codes"])
        self.assertIsNone(report["source_age_seconds"])

    def test_account_placeholders_are_not_configured_accounts(self):
        targets = {profile: dict(id=index, name="YOUR_ACCOUNT", role=role, gate_id=index)
                   for profile, index, role in (("practice", 1, "Not assigned"), ("leader", 2, "Leader"))}
        with patch("goxtrade.config.execution_identity.current_targets", return_value=targets):
            self.assertFalse(any(diagnostics.configuration()["profiles"].values()))

    def test_legacy_profile_expiration_difference_is_explicit(self):
        from goxtrade.strategies.entry_confirmation import window_open
        signal = dict(signal_minutes=15, setup_time="2026-10-22T14:45:00Z")
        self.assertTrue(window_open(signal, "2026-10-22T15:06:00Z", profile="practice"))
        self.assertTrue(window_open(signal, "2026-10-22T15:06:00Z", profile="research"))
        self.assertFalse(window_open(signal, "2026-10-22T15:06:00Z", profile="leader"))


class OperationalEvidenceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name)/"live.db"
        patcher = patch.object(live_store, "DB_PATH", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.targets = {profile: dict(id=number, name=f"PRIVATE-{profile}", role=role, gate_id=number)
                        for profile, number, role in (("practice", 99991, "Not assigned"), ("leader", 99992, "Leader"))}
        patcher = patch.object(evidence.execution_identity, "current_targets", return_value=self.targets)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_missing_stores_do_not_become_healthy_or_create_files(self):
        with patch("goxtrade.execution.projectx_client.login", side_effect=AssertionError("No login")), patch("goxtrade.execution.projectx_client.post", side_effect=AssertionError("No broker")):
            result = evidence.overview()
        self.assertEqual(result["production"]["storage"], "MISSING")
        self.assertEqual(result["research"]["storage"], "MISSING")
        self.assertEqual(result["replay"]["storage"], "MISSING")
        self.assertEqual(len(result["strategies"]), 7)
        self.assertTrue(all(row["latest_signal"] == "UNKNOWN" for row in result["strategies"]))
        self.assertEqual(list(self.path.parent.iterdir()), [])

    def populate(self):
        with closing(sqlite3.connect(self.path)) as conn:
            conn.executescript("CREATE TABLE practice_control(id INTEGER PRIMARY KEY,settings TEXT); CREATE TABLE practice_jobs(alert_id INTEGER,record TEXT); CREATE TABLE practice_history_status(id INTEGER,record TEXT); CREATE TABLE practice_loss_gate(id INTEGER,record TEXT); CREATE TABLE manager_decisions(record TEXT);")
            conn.execute("INSERT INTO practice_control VALUES(1,?)", (json.dumps(dict(enabled=False)),))
            conn.execute("INSERT INTO practice_jobs VALUES(1,?)", (json.dumps(dict(state="Unknown", account_id=99991, protected=True)),))
            conn.execute("INSERT INTO practice_history_status VALUES(1,?)", (json.dumps(dict(account_id=99991,error=False,updated_at="2000-01-01T00:00:00Z",positions=[],orders=[])),))
            conn.execute("INSERT INTO practice_loss_gate VALUES(99991,?)", (json.dumps(dict(account_id=99991,locked=True)),))
            conn.execute("INSERT INTO manager_decisions VALUES(?)", (json.dumps(dict(strategy_id="crt", selected=False,eligibility="RISK_BLOCKED",reasons=["Account PRIVATE-practice 99991 FIXTURE-KEY locked"])),))
            conn.commit()

    def test_stale_broker_state_is_not_flat_locks_and_history_preserved(self):
        self.populate()
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with patch.dict("os.environ", TOPSTEP_API_KEY="FIXTURE-KEY"):
            result = evidence.overview()
        saved = result["production"]["evidence"]["profiles"]["practice"]
        self.assertFalse(saved["saved_enabled"])
        self.assertTrue(saved["loss_locked"])
        self.assertEqual(saved["unresolved_jobs"], 1)
        self.assertIsNone(saved["broker_positions"])
        self.assertIsNone(saved["broker_orders"])
        self.assertEqual(saved["broker_protection"], "NOT VERIFIED BY THIS PAGE")
        serialized = json.dumps(result)
        for private in ("99991", "PRIVATE-practice", "FIXTURE-KEY"):
            self.assertNotIn(private, serialized)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)

    def test_practice_rejection_is_scoped_to_actual_account_and_execution(self):
        self.populate()
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute('ALTER TABLE manager_decisions ADD COLUMN scope TEXT')
            conn.execute('ALTER TABLE manager_decisions ADD COLUMN account TEXT')
            for scope,account,reason in (('practice_automation','99991','Actual Practice cooldown'),('practice_automation','99992','Other account'),('shadow','99991','Research shadow only')):
                conn.execute('INSERT INTO manager_decisions VALUES(?,?,?)',(json.dumps(dict(strategy_id='crt',selected=False,eligibility='RISK_BLOCKED',reasons=[reason])),scope,account))
            conn.commit()
        row=next(r for r in evidence.overview()['strategies'] if r['id']=='crt')
        self.assertEqual(row['last_practice_rejection'],'Actual Practice cooldown')
        self.assertEqual(row['last_rejection'],'Research shadow only')

    def test_unavailable_database_is_unknown_not_zero(self):
        self.populate()
        with closing(sqlite3.connect(self.path)) as writer:
            writer.execute("BEGIN EXCLUSIVE")
            result = evidence.overview()
            self.assertEqual(result["production"]["storage"], "UNAVAILABLE")
            self.assertIsNone(result["production"]["evidence"])
            self.assertNotIn(str(self.path), json.dumps(result))
            writer.rollback()
        self.assertEqual(evidence.overview()["production"]["storage"], "READABLE")

    def test_malformed_record_fails_closed_without_disclosing_contents(self):
        self.populate()
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("UPDATE practice_control SET settings=?", ('["PRIVATE"]',))
            conn.commit()
        result = evidence.overview()
        self.assertEqual(result["production"]["storage"], "UNAVAILABLE")
        self.assertNotIn("PRIVATE", json.dumps(result))


class ReplayOperationalRecoveryTests(unittest.TestCase):
    setUp = replay_fixtures.ReplayTests.setUp
    source = replay_fixtures.ReplayTests.source
    finish = replay_fixtures.ReplayTests.finish

    def test_stop_and_restore_open_trade_never_duplicates_entry(self):
        replay, store = replay_fixtures.replay, replay_fixtures.store
        with patch("goxtrade.research.validation_lab.candidates_at", side_effect=self.source):
            identifier = replay.create(self.request)["id"]
            for _ in range(3):
                replay.action(identifier, dict(action="step"))
            before = store.get(identifier)
            self.assertEqual(len(before["state"]["positions"]), 1)
            replay.action(identifier, dict(action="stop"))
            replay.loaded.cache_clear()
            restored = replay.detail(identifier)
            self.assertEqual(restored["status"], "stopped")
            self.assertEqual(store.get(identifier)["state"], before["state"])
            replay.action(identifier, dict(action="speed", speed="maximum"))
            replay.action(identifier, dict(action="resume"))
            player = replay._players[identifier]
            player.join(10)
            self.assertFalse(player.is_alive())
            final = store.get(identifier)
            self.assertEqual(final["status"], "complete")
            self.assertEqual(len(final["state"]["trades"]), 1)
            self.assertEqual(len({row["candidate_id"] for row in final["state"]["trades"]}), 1)
            self.assertFalse(self.path.exists(), "No actual account database created")

    def test_each_speed_preserves_step_decisions_and_cold_restart_is_empty(self):
        replay, store = replay_fixtures.replay, replay_fixtures.store
        results = []
        with patch("goxtrade.research.validation_lab.candidates_at", side_effect=self.source):
            for speed in (1, 5, 10, 30, 60, "maximum"):
                identifier = replay.create(self.request)["id"]
                replay.action(identifier, dict(action="speed", speed=speed))
                final = self.finish(identifier)
                results.append(final["state"])
            self.assertTrue(all(state == results[0] for state in results))
            restarted = replay.action(identifier, dict(action="restart"))
            self.assertEqual(restarted["next_index"], 0)
            self.assertEqual(restarted["status"], "paused")
            self.assertFalse(store.get(restarted["id"])["state"]["positions"])
            self.assertEqual(store.get(identifier)["state"], final["state"])

