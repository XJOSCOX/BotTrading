import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock, call

from goxtrade.data import live_store
from goxtrade.runtime import run_live_market


class FeedStartupTests(unittest.TestCase):
    def test_library_heartbeat_runs_with_one_reconnect_owner_and_always_stops(self):
        for error,stop_error in ((None,None),(OSError('fixture disconnect'),None),(None,RuntimeError('fixture cleanup'))):
            with self.subTest(error=error,stop_error=stop_error):
                callbacks={}
                hub=Mock()
                hub.transport.connection_checker.running=False
                hub.transport.connection_checker.stop.side_effect=stop_error
                hub.on_open.side_effect=lambda callback:callbacks.update(open=callback)
                hub.on_close.side_effect=lambda callback:callbacks.update(close=callback)
                def start():
                    callbacks['open']()
                    if error:
                        raise error
                    callbacks['close']()
                hub.start.side_effect=start
                builder=Mock()
                builder.with_url.return_value=builder
                builder.build.return_value=hub
                writer=Mock(gap_at=None)
                with patch.object(run_live_market,'HubConnectionBuilder',return_value=builder), \
                        patch.object(run_live_market,'TickBuffer',return_value=writer), \
                        patch.object(run_live_market,'login',return_value='fixture'), \
                        patch.object(run_live_market.feed_status,'update'), \
                        patch('goxtrade.data.feed_coverage.opened'),patch('goxtrade.data.feed_coverage.closed'):
                    if error:
                        with self.assertRaises(OSError):
                            run_live_market.run_connection([dict(symbol='NQ=F',contract_id='fixture-contract')])
                    else:
                        run_live_market.run_connection([dict(symbol='NQ=F',contract_id='fixture-contract')])
                hub.transport.connection_checker.start.assert_called_once()
                hub.transport.connection_checker.stop.assert_called_once()
                hub.stop.assert_called_once()
                writer.close.assert_called_once()
                hub.invoke.assert_has_calls([call('SubscribeContractQuotes',['fixture-contract']),
                                             call('SubscribeContractTrades',['fixture-contract'])])
                builder.with_automatic_reconnect.assert_not_called()

    def test_confirmed_auth_rejection_does_not_loop_until_credentials_change(self):
        from goxtrade.execution.projectx_client import ProjectXAuthError
        with tempfile.TemporaryDirectory() as folder,patch.object(live_store,"DB_PATH",Path(folder)/"test.db"),patch.object(run_live_market,"Thread"),patch.object(run_live_market,"load_symbols",return_value=[]),patch("dotenv.load_dotenv"),patch.object(run_live_market,"refresh_active_contracts",side_effect=ProjectXAuthError("Rejected",code="AUTH_FAILED")) as refresh,patch.object(run_live_market.time,"sleep",side_effect=[None,None,StopIteration]):
            with self.assertRaises(StopIteration):run_live_market.main()
        self.assertEqual(refresh.call_count,1)

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
