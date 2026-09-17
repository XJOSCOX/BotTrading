import unittest
from unittest.mock import patch
import requests
import practice_executor as executor


class ConnectionRecoveryTests(unittest.TestCase):
    def check_error(self, error, retryable):
        with patch.object(executor, "pause") as pause, patch.object(executor, "status"), patch.object(executor.bot_audit, "emit"):
            self.assertEqual(executor.recover_connection(error), retryable)
            self.assertEqual(pause.call_count, 0 if retryable else 1)

    def test_transport_preserves_run_or_manual_pause(self):
        for error in (requests.Timeout(), requests.ConnectionError()):
            self.check_error(error, True)

    def test_http_classification(self):
        for code in (401, 408, 429, 500, 503, 400, 403):
            response = requests.Response()
            response.status_code = code
            self.check_error(requests.HTTPError(response=response), code not in (400, 403))

    def test_unexpected_error_still_pauses(self):
        self.check_error(RuntimeError("identity mismatch"), False)
