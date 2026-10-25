import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import requests
from goxtrade.diagnostics import projectx_diagnostics as diag,feed_status
from goxtrade.data import live_store
from goxtrade.execution import projectx_client


def response(status=200,**values):
    result=Mock(status_code=status)
    result.json.return_value=values
    return result


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.directory=Path(directory.name)
        diag._auth.clear();diag._results.clear();diag._last=0
        for mock in (patch.object(live_store,"DB_PATH",self.directory/"live.db"),
            patch.dict("os.environ",{"TOPSTEP_USERNAME":"fixture-user","TOPSTEP_API_KEY":"TOP-SECRET-KEY","PROJECTX_API_URL":"https://api.topstepx.com"}),
            patch("goxtrade.execution.projectx_client.post",side_effect=AssertionError("No broker API"))):
            mock.start();self.addCleanup(mock.stop)

    def probe(self,transport):
        diag._last=0
        return diag.run(dict(action="authenticate"),transport=transport,sleep=lambda _:None)

    def test_invalid_auth_not_retried_or_raw_response_exposed(self):
        transport=Mock(return_value=response(success=False,errorCode=3,errorMessage="TOP-SECRET-KEY",token="SECRET-TOKEN"))
        report=self.probe(transport)
        self.assertEqual(report["code"],"AUTH_FAILED")
        self.assertEqual(report["http_status"],200)
        self.assertIn("duration_ms",report)
        transport.assert_called_once()
        self.assertNotIn("SECRET",json.dumps(report))
        self.assertFalse(diag._auth)

    def test_explicit_auth_token_memory_only_and_overview_safe(self):
        result=self.probe(Mock(return_value=response(success=True,token="SECRET-TOKEN")))
        self.assertEqual(result["code"],"OK")
        with patch.object(diag,"passive",return_value={}):saved=diag.overview()
        self.assertTrue(saved["authenticated"])
        self.assertNotIn("SECRET",json.dumps(saved))
        self.assertFalse((self.directory/"offline_replay.db").exists())

    def test_http_auth_permission_rate_limit_and_provider_classification(self):
        for status,code in ((401,"AUTH_FAILED"),(403,"PERMISSION_DENIED"),(429,"RATE_LIMITED"),(503,"PROVIDER_ERROR")):
            transport=Mock(return_value=response(status))
            self.assertEqual(self.probe(transport)["code"],code)
            transport.assert_called_once()
        for code in (7,9,10):self.assertEqual(self.probe(Mock(return_value=response(success=False,errorCode=code)))["code"],"PERMISSION_DENIED")

    def history(self,transport):
        diag._auth.update(token="SECRET-TOKEN",at="2026-10-24T00:00:00Z");diag._last=0
        def provider(url,**kwargs):
            if url.endswith("searchById"):return response(success=True,contract=dict(id="CON.F.US.MNQ.Z26",tickSize=.25,tickValue=.5))
            return transport(url,**kwargs)
        return diag.run(dict(action="history",symbol="MNQ",contract_id="CON.F.US.MNQ.Z26",start="2026-10-22T15:00:00Z",end="2026-10-22T15:05:00Z"),transport=provider,sleep=lambda _:None)

    def test_empty_history_is_not_outage_and_readonly_allowlist(self):
        transport=Mock(return_value=response(success=True,bars=[]))
        result=self.history(transport)
        self.assertEqual(result["code"],"HISTORY_UNAVAILABLE")
        self.assertEqual(result["candles"],0)
        self.assertTrue(transport.call_args.args[0].endswith("/api/History/retrieveBars"))
        with self.assertRaises(ValueError):diag._request("/api/Order/place",{})

    def test_history_retry_bounded_and_expired_token_not_reauthenticated(self):
        transport=Mock(return_value=response(429))
        self.assertEqual(self.history(transport)["code"],"RATE_LIMITED")
        self.assertEqual(transport.call_count,3)
        transport=Mock(return_value=response(401))
        self.assertEqual(self.history(transport)["code"],"AUTH_EXPIRED")
        transport.assert_called_once();self.assertFalse(diag._auth)
        transport=Mock(return_value=response(404))
        self.assertEqual(self.history(transport)["code"],"CONTRACT_NOT_FOUND")

    def test_timeout_and_malformed_sanitized(self):
        transport=Mock(side_effect=requests.Timeout("SECRET-TOKEN"))
        self.assertEqual(self.history(transport)["code"],"NETWORK_TIMEOUT")
        self.assertEqual(transport.call_count,3)
        transport=Mock(return_value=response(success=True,bars=[{"t":"SECRET-TOKEN"}]))
        report=self.history(transport)
        self.assertEqual(report["code"],"MALFORMED_RESPONSE")
        self.assertNotIn("SECRET",json.dumps(report))

    def test_valid_ohlcv_timestamp_and_volume_report(self):
        bars=[dict(t=f"2026-10-22T15:0{i}:00Z",o=100.,h=101.,l=99.,c=100.,v=10.) for i in range(5)]
        report=self.history(Mock(return_value=response(success=True,bars=bars)))
        self.assertEqual(report["code"],"OK")
        self.assertEqual(report["quality"]["invalid_candles"],0)
        self.assertIsNone(report["quality"]["coverage_percent"])

    def test_market_closed_not_stale_outage_and_unknown_not_connected(self):
        with patch("goxtrade.runtime.live_process._pid_running",return_value=True):
            feed_status.update("connected",subscriptions=[dict(symbol="MNQ=F",contract_id="CON.F.US.MNQ.Z26")])
            closed=diag.passive("2026-10-24T15:00:00Z")
            self.assertIn("MARKET_CLOSED",closed["market_codes"])
            self.assertNotIn("FEED_STALE",closed["market_codes"])
            self.assertEqual(closed["connection"],"connected")
            opened=diag.passive("2026-10-22T15:00:00Z")
            self.assertIn("FEED_STALE",opened["market_codes"])
            feed_status.update("disconnected",error="SUBSCRIPTION_FAILED",reconnect=True)
            bad=diag.passive("2026-10-22T15:00:00Z")
            self.assertIn("SUBSCRIPTION_FAILED",bad["market_codes"])
            self.assertIn("WEBSOCKET_DISCONNECTED",bad["market_codes"])
            self.assertEqual(bad["reconnection_attempts"],1)
        self.assertFalse((self.directory/"live.db").exists())

    def test_host_boundary_blocks_credential_forwarding_and_passive_no_auth(self):
        for url in ("http://api.topstepx.com","https://evil.example","https://api.topstepx.com@evil.example","https://api.topstepx.com?token=SECRET","https://api.topstepx.com:bad"):
            self.assertFalse(diag.endpoint(url)["valid"])
        with patch.object(diag,"requests") as network:
            diag.configuration();diag.passive("2026-10-24T15:00:00Z")
            network.post.assert_not_called()

    def test_existing_login_sanitized_and_structured_rejection(self):
        with patch.object(projectx_client.requests,"post",return_value=response(success=False,errorCode=3,token="SECRET-TOKEN")):
            with self.assertRaises(projectx_client.ProjectXAuthError) as caught:projectx_client.login()
            self.assertEqual(caught.exception.code,"AUTH_FAILED")
            self.assertNotIn("SECRET",str(caught.exception))

    def test_windows_process_inspection_never_sends_a_signal(self):
        feed_status.update("connected")
        with patch("goxtrade.runtime.live_process._pid_running",return_value=True) as check,patch.object(diag.os,"kill",side_effect=AssertionError("Diagnostics must not signal any process")):
            self.assertEqual(diag.passive("2026-10-24T15:00:00Z")["connection"],"connected")
            check.assert_called_once()

    def test_contract_lookup_identity_mismatch_and_missing_prevent_history_probe(self):
        body=dict(action="history",symbol="MNQ",contract_id="CON.F.US.MNQ.Z26",start="2026-10-22T15:00:00Z",end="2026-10-22T15:05:00Z")
        for contract,code in ((None,"CONTRACT_NOT_FOUND"),({"id":"wrong","tickSize":.25,"tickValue":.5},"MALFORMED_RESPONSE")):
            diag._auth.update(token="SECRET-TOKEN");diag._last=0
            transport=Mock(return_value=response(success=True,contract=contract))
            self.assertEqual(diag.run(body,transport=transport)["code"],code)
            transport.assert_called_once()


if __name__=="__main__":unittest.main()
