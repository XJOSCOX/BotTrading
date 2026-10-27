from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from goxtrade.api import app as api_module, state
from goxtrade.data import live_store
from goxtrade.execution import projectx_client, practice_executor
from goxtrade.runtime import native_app


class NativeApiTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = patch.object(live_store, "DB_PATH", Path(folder.name)/"api.db")
        patcher.start(); self.addCleanup(patcher.stop)
        cache = patch.object(state, "CACHE", state.SnapshotCache())
        cache.start(); self.addCleanup(cache.stop)
        self.base = f"http://127.0.0.1:{api_module.PORT}"
        self.app = api_module.create_app()
        self.client = TestClient(self.app, base_url=self.base, raise_server_exceptions=False)
        self.addCleanup(self.client.close)
        response = self.client.get("/api/session")
        self.assertEqual(response.status_code, 200)
        self.headers = {"origin": self.base, "x-gox-csrf": response.json()["csrf"]}

    def post(self, path, values):
        return self.client.post(path, json=values, headers=self.headers)

    def test_alert_entry_reasons_survive_event_feed_limit_and_stay_profile_scoped(self):
        from goxtrade.bot import bot_audit
        with closing(live_store.connect()) as conn:
            bot_audit.init(conn)
            def event(topic, alert, detail, kind="Entry blocked"):
                conn.execute("INSERT INTO bot_events(topic,alert_id,kind,detail) VALUES(?,?,?,?)",
                             (topic, alert, kind, detail))
            event("decision:42", 42, "Old Practice reason")
            event("leader:decision:42", 42, "Leader disabled")
            event("decision:42", 42, "Cooldown remains active")
            for index in range(110):
                event(f"noise:{index}", None, "Unrelated event", "Monitoring")
            tables = {"bot_events"}
            practice = state.alert_entry_decisions(conn, tables, [42, 43], "practice")
            leader = state.alert_entry_decisions(conn, tables, [42], "leader")
            self.assertEqual(practice[42]["detail"], "Cooldown remains active")
            self.assertEqual(practice[42]['previous'][0]['detail'],'Old Practice reason')
            self.assertEqual(leader[42]["detail"], "Leader disabled")
            self.assertNotIn(43, practice)
            self.assertEqual(state.alert_entry_decisions(conn, set(), [42], "practice"), {})
            self.assertEqual(state.alert_entry_decisions(conn, tables, [], "practice"), {})
            self.assertEqual(len(state.alert_entry_decisions(conn, tables, range(600), "practice")), 1)
            event('decision:42',42,'Manager: Signal entry window expired')
            expired=state.alert_entry_decisions(conn,tables,[42],'practice')[42]
            self.assertIn('expired',expired['detail'])
            self.assertEqual([item['detail'] for item in expired['previous']],['Cooldown remains active','Old Practice reason'])

    def test_old_broker_jobs_remain_excluded_from_watch_history(self):
        with closing(live_store.connect()) as conn:
            conn.execute("CREATE TABLE practice_jobs (alert_id INTEGER PRIMARY KEY,record TEXT)")
            for alert_id in range(1, 303):
                conn.execute("INSERT INTO practice_jobs VALUES (?,?)", (alert_id, json.dumps(
                    dict(alert_id=alert_id, state="Closed", fill_price=100, sent_at=alert_id))))
            conn.execute("INSERT INTO practice_jobs VALUES (303,?)", (json.dumps(dict(alert_id=303, state="Rejected")),))
            conn.commit()
            record = state.profile_state(conn, {"practice_jobs"}, "practice")
            self.assertEqual(len(record["jobs"]), 300)
            self.assertIn(1, record["execution_alert_ids"])
            self.assertNotIn(303, record["execution_alert_ids"])
            self.assertEqual(len(record["execution_alert_ids"]), 302)

    def test_no_session_cannot_read_financial_data(self):
        self.client.cookies.clear()
        self.assertEqual(self.client.get("/api/snapshot").status_code, 401)

    def test_host_and_cross_site_requests_are_rejected(self):
        self.assertEqual(self.client.get("/api/session", headers={"host":"evil.example"}).status_code, 403)
        self.assertEqual(self.client.get("/api/config", headers={"sec-fetch-site":"cross-site"}).status_code, 403)
        self.assertEqual(self.client.post("/api/intervals", json={}, headers={**self.headers,"origin":"https://evil.example"}).status_code, 403)
        self.assertEqual(self.client.post("/api/intervals", json={}, headers={"origin":self.base}).status_code, 403)

    def test_read_endpoints_never_login_or_start_workers(self):
        with patch.object(projectx_client, "post", side_effect=AssertionError("No provider calls")) as broker, \
                patch.object(projectx_client, "login", side_effect=AssertionError("No authentication")) as login, \
                patch.object(subprocess, "Popen", side_effect=AssertionError("No worker start")) as process, \
                patch("goxtrade.runtime.live_process.status", return_value=dict(running=False,pid=None)):
            for path in ("/api/config", "/api/snapshot", "/api/research"):
                result = self.client.get(path)
                self.assertEqual(result.status_code, 200, result.text)
            broker.assert_not_called(); login.assert_not_called(); process.assert_not_called()

    def test_chart_query_strings_are_validated_and_never_fetch_provider(self):
        with patch.object(api_module, "chart_data", return_value=dict(points=[])) as chart:
            self.assertEqual(self.client.get("/api/chart?symbol=NQ%3DF&minutes=5&hours=48").status_code, 200)
            chart.assert_called_once_with("NQ=F", 5, 48)
            self.assertEqual(self.client.get("/api/chart?symbol=NQ%3DF&minutes=4&hours=48").status_code, 400)
            self.assertEqual(self.client.get("/api/chart?symbol=OTHER&minutes=5&hours=48").status_code, 422)

    def test_validation_errors_never_echo_credential_inputs(self):
        secret = "THIS_IS_A_TEST_SECRET_NOT_A_REAL_KEY"
        response = self.post("/api/credentials", dict(username="", api_key=secret, extra=secret))
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(secret, response.text)

    def test_credentials_cannot_change_while_workers_run(self):
        with patch("goxtrade.execution.account_management.assert_workers_stopped", side_effect=ValueError("Stop workers first")), \
                patch.object(projectx_client, "save_credentials") as save:
            self.assertEqual(self.post("/api/credentials", dict(username="test",api_key="test-key")).status_code, 400)
            save.assert_not_called()

    def test_service_commands_require_csrf_and_validate_actions(self):
        with patch("goxtrade.runtime.service_control.command", return_value=dict(message="Test only", services={})) as command:
            self.assertEqual(self.client.post("/api/services/start", json={}).status_code, 403)
            command.assert_not_called()
            for action in ("start", "restart", "stop"):
                self.assertEqual(self.post("/api/services/" + action, {}).status_code, 200)
            self.assertEqual(command.call_count, 3)
            self.assertEqual(self.post("/api/services/invalid", {}).status_code, 422)
            self.assertEqual(command.call_count, 3)

    def test_service_status_does_not_issue_commands(self):
        with patch("goxtrade.runtime.service_control.status", return_value={"market": {"running": False}}), \
                patch("goxtrade.runtime.service_control.command") as command:
            self.assertEqual(self.client.get("/api/services").status_code, 200)
            command.assert_not_called()

    def test_credential_guard_describes_credentials_not_account_replacement(self):
        with patch("goxtrade.runtime.live_process.status", return_value=dict(running=True)), \
                patch.object(projectx_client, "save_credentials") as save:
            response = self.post("/api/credentials", dict(username="test", api_key="test-key"))
            self.assertEqual(response.status_code, 400)
            self.assertIn("changing API credentials", response.json()["detail"])
            self.assertIn("Pause & stop trading workers", response.json()["detail"])
            self.assertNotIn("replacing an account", response.text)
            self.assertNotIn("test-key", response.text)
            save.assert_not_called()

    def test_credentials_save_only_after_worker_and_idle_checks(self):
        with patch("goxtrade.execution.account_management.assert_workers_stopped") as stopped, \
                patch("goxtrade.execution.account_management.assert_idle") as idle, \
                patch.object(projectx_client, "save_credentials") as save:
            response = self.post("/api/credentials", dict(username="test", api_key="test-key"))
            self.assertEqual(response.status_code, 200)
            self.assertIn("changing API credentials", stopped.call_args.kwargs["action"])
            self.assertEqual(idle.call_args.kwargs["action"], "changing API credentials")
            save.assert_called_once_with("test", "test-key")

    def test_credentials_do_not_save_with_unresolved_orders(self):
        with patch("goxtrade.execution.account_management.assert_workers_stopped"), \
                patch("goxtrade.execution.account_management.assert_idle", side_effect=ValueError("Resolve every open, pending or uncertain bot order first")), \
                patch.object(projectx_client, "save_credentials") as save:
            response = self.post("/api/credentials", dict(username="test", api_key="test-key"))
            self.assertEqual(response.status_code, 400)
            save.assert_not_called()

    def test_policy_accepts_leader_indicator_selection_but_refuses_invalid_quantity(self):
        policy = dict(strategies=["VWAP EMA Cross"], quantities=dict(MNQ=2,MES=2,MYM=2), cooldown=5, enable_mym=False)
        with patch("goxtrade.execution.leader_execution.command") as command:
            self.assertEqual(self.post("/api/policy/leader", policy).status_code, 200)
            command.assert_called_once()
            self.assertEqual(command.call_args.args[0],"configure")
        for quantity in (5, True, 2.5):
            policy["quantities"]["MNQ"] = quantity
            self.assertEqual(self.post("/api/policy/practice", policy).status_code, 422)

    def test_policy_save_does_not_arm(self):
        with patch.object(practice_executor, "configure") as configure, patch.object(practice_executor, "arm") as arm:
            response = self.post("/api/policy/practice", dict(strategies=["CRT"],quantities=dict(MNQ=3,MES=2,MYM=1),cooldown=9,enable_mym=False))
            self.assertEqual(response.status_code, 200, response.text)
            configure.assert_called_once_with(dict(MNQ=3,MES=2,MYM=1),False)
            arm.assert_not_called()

    def test_single_instrument_selection_survives_explicit_and_legacy_saves(self):
        from goxtrade.bot import bot_controls
        original_leader=bot_controls.read('leader')
        body=dict(strategies=['CRT'],quantities=dict(MNQ=1,MES=3,MYM=3),cooldown=5,enable_mym=False,symbols=['MNQ'])
        with patch.object(practice_executor,'arm') as arm,patch.object(projectx_client,'post',side_effect=AssertionError('No broker calls')):
            self.assertEqual(self.post('/api/policy/practice',body).status_code,200)
            self.assertEqual(bot_controls.read('practice')['symbols'],['MNQ'])
            del body['symbols']
            self.assertEqual(self.post('/api/policy/practice',body).status_code,200)
            self.assertEqual(bot_controls.read('practice')['symbols'],['MNQ'])
            self.assertEqual(bot_controls.read('leader'),original_leader)
            arm.assert_not_called()
        for symbols in (['MNQ','MNQ'],['MYM']):
            self.assertEqual(self.post('/api/policy/practice',{**body,'symbols':symbols}).status_code,400)
            self.assertEqual(bot_controls.read('practice')['symbols'],['MNQ'])

    def test_policy_round_trip_uses_saved_settings_not_cached_runtime(self):
        from goxtrade.bot import bot_controls
        with patch.object(practice_executor, "arm") as arm, patch.object(projectx_client, "post", side_effect=AssertionError("No broker calls")):
            for strategies, enabled, quantity in ((["CRT", "Reversal"], True, 4), ([], False, 1), (["ORB"], True, 2)):
                with self.subTest(strategies=strategies):
                    state.CACHE.get()
                    body = dict(strategies=strategies, quantities=dict(MNQ=quantity,MES=3,MYM=2), cooldown=17, enable_mym=enabled)
                    response = self.post("/api/policy/practice", body)
                    self.assertEqual(response.status_code, 200, response.text)
                    saved = self.client.get("/api/config").json()
                    self.assertEqual(saved["policies"]["practice"]["strategies"], strategies)
                    self.assertEqual(saved["policies"]["practice"]["cooldown_minutes"], 17)
                    self.assertEqual("MYM" in saved["policies"]["practice"]["symbols"], enabled)
                    self.assertEqual(saved["execution_settings"]["practice"]["quantities"], body["quantities"])
                    self.assertEqual(saved["execution_settings"]["practice"]["enable_mym"], enabled)
                    self.assertFalse(saved["execution_settings"]["practice"].get("enabled", False))
            arm.assert_not_called()

    def test_policy_preserves_running_state_runtime_and_other_profile(self):
        settings = dict(enabled=True, quantities=dict(MNQ=2,MES=2,MYM=2), start_balance=50000, custom_guard=True)
        with closing(practice_executor.db()) as conn:
            conn.execute("UPDATE practice_control SET settings=?,status=? WHERE id=1", (json.dumps(settings), json.dumps(dict(message="runtime kept"))))
            conn.commit()
        with patch.object(projectx_client, "post", side_effect=AssertionError("No broker calls")):
            response = self.post("/api/policy/practice", dict(strategies=[],quantities=dict(MNQ=4,MES=1,MYM=3),cooldown=11,enable_mym=True))
        self.assertEqual(response.status_code, 200, response.text)
        saved, runtime, _ = practice_executor.snapshot()
        self.assertTrue(saved["enabled"])
        self.assertEqual(saved["start_balance"], 50000)
        self.assertTrue(saved["custom_guard"])
        self.assertEqual(runtime["message"], "runtime kept")
        self.assertEqual(self.client.get("/api/config").json()["execution_settings"]["leader"], {})

    def test_invalid_policy_does_not_write_any_settings(self):
        before = self.client.get("/api/config").json()
        with patch.object(practice_executor, "configure") as configure:
            response = self.post("/api/policy/practice", dict(strategies=["UNKNOWN"],quantities=dict(MNQ=2,MES=2,MYM=2),cooldown=5,enable_mym=False))
            self.assertEqual(response.status_code, 400)
            configure.assert_not_called()
        after = self.client.get("/api/config").json()
        self.assertEqual(before["policies"], after["policies"])
        self.assertEqual(before["execution_settings"], after["execution_settings"])

    def test_all_interval_options_and_vwap_settings_persist_without_arming(self):
        with patch.object(practice_executor, "arm") as arm, patch.object(projectx_client, "post", side_effect=AssertionError("No broker calls")):
            for stop in (5,10,15):
                for orb in (5,15,30):
                    response = self.post("/api/intervals",dict(stop_minutes=stop,orb_minutes=orb))
                    self.assertEqual(response.status_code,200,response.text)
                    saved = self.client.get("/api/config").json()
                    self.assertEqual((saved["stop_minutes"],saved["orb_minutes"]),(stop,orb))
            self.assertEqual(self.post("/api/intervals",dict(stop_minutes=1,orb_minutes=5)).status_code,422)
            for enabled in (True,False):
                response=self.post("/api/vwap",dict(monitor_enabled=enabled,practice_enabled=enabled,signal_minutes=5,ema_length=12))
                self.assertEqual(response.status_code,200,response.text)
                saved=self.client.get("/api/config").json()["vwap"]
                self.assertEqual((saved["monitor_enabled"],saved["practice_enabled"],saved["signal_minutes"],saved["ema_length"]),(enabled,enabled,5,12))
            arm.assert_not_called()

    def test_box_settings_round_trip_never_arms_and_leader_is_selectable(self):
        with patch.object(practice_executor,"arm") as arm,patch("goxtrade.execution.leader_execution.command") as leader:
            response=self.post("/api/previous-day-box",dict(session="rth",buy_percent=20,sell_percent=80,practice_enabled=True))
            self.assertEqual(response.status_code,200,response.text)
            saved=self.client.get("/api/config").json()["previous_day_box"]
            self.assertEqual((saved["session"],saved["buy_percent"],saved["sell_percent"]),("rth",20,80))
            self.assertFalse(saved["paper_enabled"])
            response=self.post("/api/policy/leader",dict(strategies=["Previous Day Box Reversal"],quantities=dict(MNQ=3,MES=3,MYM=3),cooldown=5,enable_mym=False))
            self.assertEqual(response.status_code,200)
            arm.assert_not_called()
            leader.assert_called_once()
            self.assertEqual(leader.call_args.args[0],"configure")
            self.assertFalse(saved["leader_enabled"])

    def test_box_view_uses_local_data_without_provider_calls(self):
        with patch.object(projectx_client,"post",side_effect=AssertionError("No broker calls")):
            response=self.client.get("/api/previous-day-box/NQ%3DF")
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()["signal"]["signal"],"WAIT")

    def test_arm_requires_exact_name_safeguards_and_fresh_account_worker(self):
        target = api_module.identity.TARGETS["practice"]
        with patch.object(practice_executor, "arm") as arm, patch.object(practice_executor,"snapshot",return_value=({}, {}, [])):
            for body in (dict(name="WRONG",safeguards=True),dict(name=target["name"],safeguards=False),dict(name=target["name"],safeguards=True)):
                self.assertEqual(self.post("/api/execution/practice/arm", body).status_code, 400)
            arm.assert_not_called()

    def test_explicit_authorization_delegates_existing_safety_once_no_retry(self):
        target = api_module.identity.TARGETS["practice"]
        settings = dict(quantities=dict(MNQ=3,MES=2,MYM=1),enable_mym=False)
        from goxtrade.execution.safeguards import PROTOCOL_VERSION
        from goxtrade.runtime.build_identity import fingerprint
        runtime = dict(updated_at=datetime.now(timezone.utc).isoformat(),account_id=target["id"],practice_automation=True,safeguards_version=PROTOCOL_VERSION,worker_build=fingerprint())
        body = dict(name=target["name"],safeguards=True,quantities=settings["quantities"],strategies=["crt"])
        with patch.object(practice_executor, "snapshot", return_value=(settings,runtime,[])), \
                patch("goxtrade.execution.practice_automation.start", side_effect=RuntimeError("Mocked broker unavailable")) as start:
            self.assertEqual(self.post("/api/execution/practice/start", body).status_code, 503)
            start.assert_called_once_with(["crt"],target["name"],True,confirmed_quantities=settings["quantities"],acknowledge_loss=False)

    def test_retired_practice_start_paths_cannot_bypass_manager(self):
        target=api_module.identity.TARGETS["practice"]
        body=dict(name=target["name"],safeguards=True)
        with patch.object(practice_executor,"arm") as arm:
            self.assertEqual(self.post('/api/execution/practice/arm',body).status_code,400)
            self.assertEqual(self.post('/api/execution/practice/strategy-test',body).status_code,422)
            arm.assert_not_called()

    def test_stale_worker_build_cannot_authorize_entries(self):
        target=api_module.identity.TARGETS['practice']
        from goxtrade.execution.safeguards import PROTOCOL_VERSION
        runtime=dict(updated_at=datetime.now(timezone.utc).isoformat(),account_id=target['id'],practice_automation=True,safeguards_version=PROTOCOL_VERSION,worker_build='old-source')
        body=dict(name=target['name'],safeguards=True,quantities=dict(MNQ=1,MES=1,MYM=1),strategies=['crt'])
        with patch.object(practice_executor,'snapshot',return_value=({},runtime,[])),patch('goxtrade.execution.practice_automation.start') as start:
            self.assertEqual(self.post('/api/execution/practice/start',body).status_code,400)
            start.assert_not_called()

    def test_safeguard_save_is_persistent_and_does_not_apply_or_arm(self):
        original=self.client.get('/api/safeguards/practice').json()
        body=dict(revision=original['revision'],loss_lock=1000.,max_contracts=2,max_trade_risk=100.,max_open_risk=200.,overnight_max_contracts=2,overnight_cooldown_minutes=7,overnight_max_spread_ticks=3)
        with patch.object(projectx_client,'post',side_effect=AssertionError('No broker mutation or reads needed for Save')),patch.object(practice_executor,'arm') as arm:
            response=self.post('/api/safeguards/practice',body)
            self.assertEqual(response.status_code,200,response.text)
            record=self.client.get('/api/safeguards/practice').json()
            self.assertEqual(record['active'],original['active'])
            self.assertEqual(record['saved']['loss_lock'],1000)
            self.assertEqual(self.post('/api/safeguards/practice',body).status_code,400)
            self.assertEqual(self.post('/api/safeguards/practice/apply',dict(name='WRONG',revision=record['revision'],confirmed=True)).status_code,400)
            arm.assert_not_called()

    def test_safeguard_apply_requires_explicit_confirmation(self):
        with patch('goxtrade.execution.safeguards.apply',return_value=dict(saved={},active={},revision=1)) as apply:
            self.assertEqual(self.post('/api/safeguards/practice/apply',dict(name='fixture',revision=0,confirmed=False)).status_code,400)
            apply.assert_not_called()
            self.assertEqual(self.post('/api/safeguards/practice/apply',dict(name='fixture',revision=0,confirmed=True)).status_code,200)
            apply.assert_called_once_with('practice','fixture',0)

    def test_startup_and_websocket_only_stream_local_records(self):
        with patch.object(projectx_client,"post",side_effect=AssertionError("No broker calls")) as broker:
            with self.client.websocket_connect(self.base.replace("http://", "ws://")+"/api/stream", headers={"origin":self.base, "cookie":"gox_session="+self.client.cookies.get("gox_session")}) as socket:
                frames=[socket.receive_json()]
                self.assertEqual(frames[0]["type"],"ticks")
                while not any(frame["type"]=="snapshot" for frame in frames):
                    frames.append(socket.receive_json())
                snapshot=next(frame for frame in frames if frame["type"]=="snapshot")
                ticks=frames[0]
                self.assertEqual(snapshot["type"],"snapshot")
                self.assertEqual(ticks["type"],"ticks")
                self.assertIn("prices",ticks["data"])
            broker.assert_not_called()

    def test_cross_site_websocket_rejected(self):
        with self.assertRaises(WebSocketDisconnect) as error:
            with self.client.websocket_connect(self.base.replace("http://", "ws://")+"/api/stream",headers={"origin":"https://evil.example"}):
                pass
        self.assertEqual(error.exception.code,1008)

    def test_broker_error_does_not_echo_auth_response(self):
        with patch.object(projectx_client,"login",side_effect=RuntimeError("SECRET_TOKEN_SAMPLE")):
            response=self.post("/api/connection/test",{})
            self.assertEqual(response.status_code,503)
            self.assertNotIn("SECRET_TOKEN_SAMPLE",response.text)

    def test_snapshot_source_types_and_no_simulated_profit_merging(self):
        data=self.client.get("/api/snapshot").json()
        self.assertEqual(data["profiles"]["practice"]["totals"]["net"],0)
        self.assertEqual(data["profiles"]["leader"]["trades"],[])

    def test_fresh_subprocess_does_not_import_streamlit(self):
        result=subprocess.run([sys.executable,"-c","from goxtrade.api.app import app; import sys; assert 'streamlit' not in sys.modules; print('independent')"],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)


class NativeLauncherTests(unittest.TestCase):
    def test_restart_only_restarts_api(self):
        with patch.object(native_app,"stop") as stop, patch.object(native_app,"start",return_value="url") as start:
            self.assertEqual(native_app.restart(),"url")
            stop.assert_called_once();start.assert_called_once_with(False)

    def test_stop_does_not_kill_child_trading_workers(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(native_app,"PID_FILE",Path(folder)/"api.pid"), \
                patch.object(native_app,"_pid_running",side_effect=[True,False]), patch.object(native_app.subprocess,"run") as run:
            native_app.PID_FILE.write_text(json.dumps(dict(pid=1234,port=8504)))
            run.side_effect=[subprocess.CompletedProcess([],0,f"python -m uvicorn goxtrade.api.app:app --app-dir {native_app.ROOT}"),subprocess.CompletedProcess([],0)]
            native_app.stop()
            task=run.call_args_list[1].args[0]
            self.assertEqual(task,["taskkill","/PID","1234","/F"])
            self.assertNotIn("/T",task)

    def test_unrelated_pid_is_not_terminated(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(native_app,"PID_FILE",Path(folder)/"api.pid"), \
                patch.object(native_app,"_pid_running",return_value=True), patch.object(native_app.subprocess,"run",return_value=subprocess.CompletedProcess([],0,"unrelated.py")) as run:
            native_app.PID_FILE.write_text(json.dumps(dict(pid=1234,port=8504)))
            with self.assertRaises(RuntimeError):native_app.stop()
            self.assertEqual(run.call_count,1)

    def test_cmd_menu_remains_open_after_restart(self):
        with patch.object(native_app,"start"),patch.object(native_app,"restart") as restart,patch("builtins.input",side_effect=["2","6"]):
            native_app.menu()
            restart.assert_called_once_with()
