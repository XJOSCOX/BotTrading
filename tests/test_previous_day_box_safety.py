from dataclasses import replace
import unittest
from unittest.mock import patch
import pandas as pd

from goxtrade.strategies.previous_day_box import validate_entry
from goxtrade.strategies.previous_day_box_config import PreviousDayBoxConfig
from goxtrade.strategies.strategy_catalog import execution_block,order_block
from goxtrade.strategies.entry_confirmation import evaluate,window_open
from tests.previous_day_box_fixtures import NOW,CONTRACT,candidate,history


class BoxSafetyTests(unittest.TestCase):
    def test_same_capabilities_with_independent_account_permission(self):
        config=PreviousDayBoxConfig()
        self.assertTrue(config.monitor_enabled);self.assertFalse(config.paper_enabled);self.assertFalse(config.practice_enabled)
        self.assertIn("Leader",execution_block(candidate(),"leader"))
        with patch("goxtrade.strategies.strategy_settings.read_previous_day_box_config",return_value=replace(config,practice_enabled=True)):
            self.assertIn("Leader",execution_block(candidate(),"leader"))
        with patch("goxtrade.strategies.strategy_settings.read_previous_day_box_config",return_value=replace(config,leader_enabled=True)):
            self.assertIsNone(execution_block(candidate(),"leader"))
            self.assertIn("Practice",execution_block(candidate(),"practice"))

    def test_practice_off_and_forged_envelopes_blocked(self):
        signal=candidate()
        self.assertIsNotNone(execution_block(signal,"practice"))
        with patch("goxtrade.strategies.strategy_settings.read_previous_day_box_config",return_value=PreviousDayBoxConfig(practice_enabled=True)):
            self.assertIsNone(execution_block(signal,"practice"))
            for values in (dict(consumption_key="fake"),dict(strategy="CRT"),dict(signal_minutes=1),dict(config_fingerprint="wrong"),dict(box={})):
                self.assertIsNotNone(execution_block({**signal,**values},"practice"))

    def test_calendar_loss_and_existing_submission_gates_not_bypassed(self):
        with patch("goxtrade.strategies.strategy_settings.read_previous_day_box_config",return_value=PreviousDayBoxConfig(practice_enabled=True)),patch("goxtrade.market.calendar_guard.entry_block",return_value="Reviewed calendar unavailable"):
            self.assertEqual(order_block(candidate(),"practice",NOW),"Reviewed calendar unavailable")
        from goxtrade.execution.practice_executor import entry_wait
        self.assertIn("Pending",entry_wait([],[],[dict(state="Unknown",alert_id=1)]))

    def test_contract_staleness_expiry_and_geometry_at_revalidation(self):
        signal={**candidate(),"status":"Active"}
        self.assertIsNone(validate_entry(signal,118,NOW,CONTRACT))
        self.assertIsNotNone(validate_entry(signal,118,NOW,"OTHER"))
        self.assertIsNotNone(validate_entry(signal,151,NOW,CONTRACT))
        self.assertFalse(window_open(signal,NOW+pd.Timedelta(seconds=90)))
        result=evaluate(signal,history(),118,NOW)
        self.assertEqual(result["state"],"Confirmed",result)
        invalid=evaluate(signal,history(),160,NOW)
        self.assertEqual(invalid["state"],"Cancelled")

    def test_nonfinite_parameters_and_unacknowledged_costs_fail(self):
        for values in (dict(paper_enabled=True),dict(minimum_effective_rr=1),dict(reward_risk=float("inf")),dict(stop_buffer_ticks=True),dict(session="calendar_day")):
            with self.assertRaises(ValueError):PreviousDayBoxConfig.from_dict(values)
