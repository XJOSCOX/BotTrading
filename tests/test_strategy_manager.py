import json
from dataclasses import FrozenInstanceError, replace
import unittest

from goxtrade.execution.strategy_manager import evaluate
from goxtrade.execution.trade_candidate import adapt_alert
from goxtrade.strategies.strategy_catalog import SPECS
from tests.manager_fixtures import NOW, candidate, facts, policy


class StrategyManagerTests(unittest.TestCase):
    def test_confirmation_reasons_are_preserved_without_allowing_unconfirmed_entries(self):
        for state,complete,reason,eligibility in (
            ('Waiting',True,'5m candle momentum does not support direction','REJECTED'),
            ('Waiting',False,'1m/5m history delayed or incomplete','DATA_UNAVAILABLE'),
            ('Cancelled',True,'Setup invalidation breached before entry','REJECTED')):
            with self.subTest(state=state,complete=complete):
                evidence=json.dumps(dict(entry_confirmation=dict(state=state,reason=reason,history_complete=complete)))
                row=candidate(confirmed=False,history_complete=complete,evidence_json=evidence)
                decision=evaluate([row],facts(),policy(),NOW)[0]
                self.assertEqual(decision.eligibility,eligibility)
                self.assertIn(reason,decision.reasons[0])
                self.assertFalse(decision.selected)

    def test_all_registered_adapters(self):
        for spec in SPECS:
            with self.subTest(spec=spec.id):
                row = candidate(spec.id)
                self.assertEqual(evaluate([row], facts(), policy(), NOW)[0].eligibility, "ELIGIBLE")
                with self.assertRaises(FrozenInstanceError):
                    row.stop = 99

    def test_expired_future_stale_missing_history(self):
        cases = [(dict(created_at="2026-10-22T14:59:00+00:00", expires_at="2026-10-22T14:59:59+00:00", confirmed_at="2026-10-22T14:59:00+00:00"), "EXPIRED"),
                 (dict(confirmed_at="2026-10-22T15:00:01+00:00"), "REJECTED"),
                 (dict(quote_at="2026-10-22T14:59:00+00:00"), "DATA_UNAVAILABLE"),
                 (dict(history_complete=False), "DATA_UNAVAILABLE"), (dict(confirmed=False), "REJECTED")]
        for changes, expected in cases:
            with self.subTest(changes=changes):
                result = evaluate([candidate(**changes)], facts(), policy(), NOW)[0]
                self.assertEqual(result.eligibility, expected)
                self.assertFalse(result.selected)

    def test_levels_and_identity_rejected(self):
        for changes in (dict(stop=None), dict(target=95), dict(price=float("nan")), dict(stop=90.1),
                        dict(account_id="other"), dict(contract_id="CON.F.US.MES.Z26"), dict(strategy_name="Other")):
            self.assertEqual(evaluate([candidate(**changes)], facts(), policy(), NOW)[0].eligibility, "REJECTED")

    def test_duplicate_and_consumption(self):
        row = candidate()
        self.assertFalse(evaluate([row, row], facts(), policy(), NOW)[0].selected)
        self.assertIn("consumed", evaluate([row], facts(consumed=(row.setup_id,)), policy(), NOW)[0].reasons[0])

    def test_missing_session_exit_ownership_and_expiry_policy_rejected(self):
        for changes in (dict(session="unspecified"), dict(management_mode="structure-v1"), dict(management_mode="trailing"),
                        dict(expires_at="2026-10-22T16:00:00+00:00")):
            self.assertFalse(evaluate([candidate(**changes)], facts(), policy(), NOW)[0].selected)

    def test_pure_reproducible_and_no_broker_claim(self):
        first = evaluate([candidate()], facts(), policy(), NOW)
        self.assertEqual(first, evaluate([candidate()], facts(), policy(), NOW))
        self.assertEqual(first[0].checks_scope, "historical_only")
        self.assertEqual(first[0].execution_status, "SIMULATION_SELECTED")

    def test_config_schema_and_credentials(self):
        from goxtrade.execution.execution_policy import ExecutionPolicy
        for values in (dict(unknown=True), dict(max_daily_loss=1000001), dict(max_contracts=5), dict(paper_enabled="yes"),
                       dict(commission_per_side=0), dict(priority=["crt", "crt"]), dict(minimum_rr=float("nan"))):
            with self.assertRaises((ValueError, TypeError)):
                ExecutionPolicy.from_dict(values)
        self.assertFalse(evaluate([candidate(config_json=json.dumps(dict(api_key="not-a-key")))], facts(), policy(), NOW)[0].selected)
