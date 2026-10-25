"""Phase 7 fault injection. No credentials, account workers or broker transport."""
import sqlite3
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch
import pandas as pd

from goxtrade.execution import practice_executor as executor, projectx_client as client
from goxtrade.execution.strategy_manager import evaluate
from goxtrade.replay import replay_session as replay, replay_store as store
from tests.manager_fixtures import candidate, facts, policy, NOW
from tests import test_offline_replay as replay_fixtures


class BrokerResponseHardeningTests(unittest.TestCase):
    def setUp(self):
        blocked = patch.object(client, "_blocked_auth", None, create=True)
        blocked.start()
        self.addCleanup(blocked.stop)

    def test_known_rejected_credentials_are_not_repeated_by_workers(self):
        response = Mock(status_code=200, json=lambda: dict(success=False, errorCode=3))
        with patch.dict(client.os.environ, TOPSTEP_USERNAME="fixture", TOPSTEP_API_KEY="fixture"), patch.object(client.requests, "post", return_value=response) as request:
            for _ in range(3):
                with self.assertRaises(client.ProjectXAuthError):
                    client.login()
            self.assertEqual(request.call_count, 1)
            response.json = lambda: dict(success=True, token="fixture-token")
            with patch.dict(client.os.environ, TOPSTEP_API_KEY="changed-fixture"):
                self.assertEqual(client.login(), "fixture-token")
            self.assertEqual(request.call_count, 2)

    def test_unknown_authentication_failure_is_not_mislabeled_as_permanent(self):
        response = Mock(status_code=200, json=lambda: dict(success=False, errorCode=999))
        with patch.dict(client.os.environ, TOPSTEP_USERNAME="fixture", TOPSTEP_API_KEY="fixture"), patch.object(client.requests, "post", return_value=response) as request:
            for _ in range(2):
                with self.assertRaises(client.ProjectXAuthError) as failure:
                    client.login()
                self.assertEqual(failure.exception.code, "UNKNOWN_ERROR")
            self.assertEqual(request.call_count, 2)

    def test_login_rejects_truthy_success_and_non_string_tokens(self):
        for body in ({"success": "false", "token": "secret"}, {"success": True, "token": 123},
                     {"success": True, "token": "  "}, [], None):
            with self.subTest(body=body), patch.dict(client.os.environ, TOPSTEP_USERNAME="fixture", TOPSTEP_API_KEY="fixture"), patch.object(client.requests, "post", return_value=Mock(status_code=200, json=lambda: body)):
                with self.assertRaises(RuntimeError):
                    client.login()

    def test_malformed_json_is_sanitized_and_never_retried(self):
        response = Mock(status_code=200)
        response.json.side_effect = ValueError("private provider response")
        with patch.object(client.requests, "post", return_value=response) as request:
            with self.assertRaisesRegex(RuntimeError, "response") as failure:
                client.post("/api/Order/place", {}, token="fixture")
            self.assertNotIn("private", str(failure.exception))
            self.assertEqual(request.call_count, 1)

    def test_non_object_order_response_is_not_a_success(self):
        for body in ([], None, "success", {"success": "true"}):
            with self.subTest(body=body), patch.object(client.requests, "post", return_value=Mock(json=lambda: body)):
                with self.assertRaises(RuntimeError):
                    client.post("/api/Order/place", {}, token="fixture")

    def test_malformed_broker_collection_is_not_flat(self):
        for positions, orders in ((None, []), ([], {}), ([None], []),
                                   ([dict(accountId=executor.ACCOUNT_ID + 1)], [])):
            with self.subTest(positions=positions, orders=orders), patch.object(executor, "call", side_effect=[dict(positions=positions), dict(orders=orders)]):
                with self.assertRaises(RuntimeError):
                    executor.account_state("fixture")

    def test_stop_requires_real_finite_tick_aligned_price(self):
        job = dict(symbol="MNQ", contract_id="CON.F.US.MNQ.Z26", order_id=10, quantity=2, side=0)
        order = dict(contractId=job["contract_id"], parentOrderId=10, size=2, side=1, type=4, stopPrice=95.)
        self.assertTrue(executor.protective_order(order, job))
        for bad in (None, True, 0, -1, float("nan"), float("inf"), "95", 95.1):
            with self.subTest(stop=bad):
                self.assertFalse(executor.protective_order({**order, "stopPrice": bad}, job))
        self.assertFalse(executor.protective_order({**order, "accountId": executor.ACCOUNT_ID+1}, job))
        # A legitimately tightened stop can be beyond the entry, on the profit side.
        self.assertTrue(executor.protective_order({**order, "stopPrice": 105.25}, job))


class RestoredRiskHardeningTests(unittest.TestCase):
    def test_mismatched_restored_contract_is_not_verified_exposure(self):
        from goxtrade.execution.portfolio_risk import Exposure, authorize_risk
        exposure = Exposure("MES", "CON.F.US.MNQ.Z26", "LONG", 1, 100., 90., "crt", "fixture", protected=True)
        result = authorize_risk(candidate(), facts(positions=(exposure,)), policy(max_positions=3, max_group_positions=3), NOW)
        self.assertFalse(result["allowed"])

    def test_restored_switches_must_be_actual_booleans(self):
        for field in ("session_allowed", "paused", "armed", "reconciled", "unresolved", "emergency", "loss_locked"):
            state = replace(facts(), **{field: "false"})
            with self.subTest(field=field):
                result = evaluate([candidate()], state, policy(), NOW, scope="historical")
                self.assertFalse(any(d.selected for d in result))
                self.assertTrue(result)


class ReplayFailureHardeningTests(unittest.TestCase):
    setUp = replay_fixtures.ReplayTests.setUp

    def test_thread_start_failure_pauses_the_saved_session(self):
        identifier = replay.create(self.request)["id"]
        with patch.object(replay.threading.Thread, "start", side_effect=RuntimeError("private OS details")):
            with self.assertRaisesRegex(RuntimeError, "Replay"):
                replay.action(identifier, dict(action="play"))
        record = store.get(identifier)
        self.assertEqual(record["status"], "paused")
        self.assertIn("error", record)
        self.assertNotIn("private", record["error"])
        self.assertNotIn(identifier, replay._players)

    def test_database_failure_does_not_raise_again_and_recovers_as_paused(self):
        identifier = replay.create(self.request)["id"]
        record = store.get(identifier)
        record.update(status="playing", generation=1)
        store.save(record)
        with patch.object(store, "get", side_effect=sqlite3.OperationalError("private path")):
            replay._play(identifier, 1)
        result = replay.detail(identifier)
        self.assertEqual(result["status"], "paused")
        self.assertIn("error", result)
        self.assertEqual(result["next_index"], 0)
        self.assertEqual(store.get(identifier)["status"], "paused")

    def test_failure_recovery_cannot_overwrite_newer_controller(self):
        identifier = replay.create(self.request)["id"]
        with patch.object(store, "get", side_effect=sqlite3.OperationalError("offline")):
            replay._play(identifier, 1)
        record = store.get(identifier)
        record.update(status="stopped", generation=2)
        store.save(record)
        self.assertEqual(replay.detail(identifier)["status"], "stopped")

    def test_chart_ema_does_not_reset_at_display_window(self):
        from goxtrade.data import lab_store
        frame = pd.DataFrame([dict(time=t, open=100+i*.25, high=101+i*.25,
                                  low=99+i*.25, close=100+i*.25, volume=10)
                              for i, t in enumerate(pd.date_range("2026-10-22T00:00Z", periods=520, freq="min"))])
        meta = {**self.meta, "start": frame.iloc[0].time.isoformat(),
                "end": (frame.iloc[-1].time+pd.Timedelta(minutes=1)).isoformat()}
        dataset = lab_store.save_dataset(frame, meta)
        request = {**self.request, "datasets": [dataset["id"]], "start": meta["start"], "end": meta["end"]}
        identifier = replay.create(request)["id"]
        record = store.get(identifier)
        record["clock"] = meta["end"]
        store.save(record)
        bars = replay.chart(identifier, "MNQ")["bars"]
        self.assertEqual(len(bars), 500)
        self.assertAlmostEqual(bars[0]["ema50"], frame.close.ewm(span=50, adjust=False).mean().iloc[20], places=10)


class ApiBoundaryHardeningTests(unittest.TestCase):
    def test_invalid_content_length_is_client_error_not_server_failure(self):
        from fastapi.testclient import TestClient
        from goxtrade.api.app import create_app, PORT
        with TestClient(create_app(), base_url=f"http://127.0.0.1:{PORT}", raise_server_exceptions=False) as browser:
            for value in ("bad", "-1", "1.5"):
                with self.subTest(value=value):
                    response = browser.get("/api/health", headers={"content-length": value})
                    self.assertEqual(response.status_code, 400)
                    self.assertNotIn(value, response.json()["detail"])

