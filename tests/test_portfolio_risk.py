import unittest
from goxtrade.execution.portfolio_risk import Exposure, authorize_risk
from tests.manager_fixtures import NOW, CONTRACT, candidate, facts, policy


class PortfolioRiskTests(unittest.TestCase):
    def test_micro_values_fees_slippage_and_sizing(self):
        result = authorize_risk(candidate(), facts(), policy(requested_quantity=4, max_trade_risk=45), NOW)
        self.assertEqual(result["quantity"], 2)
        self.assertEqual(result["planned_risk"], 44.)
        result = authorize_risk(candidate(symbol="MES"), facts(), policy(), NOW)
        self.assertEqual(result["planned_risk"], 53.5)

    def test_structural_stop_not_tightened(self):
        row = candidate(stop=50.)
        self.assertFalse(authorize_risk(row, facts(), policy(), NOW)["allowed"])
        self.assertEqual(row.stop, 50.)

    def test_correlated_limits_and_same_underlying(self):
        position = Exposure("MNQ", CONTRACT, "LONG", 1, 100., 90., "crt", "owner", protected=True)
        for row in (candidate(symbol="MES"), candidate(symbol="NQ")):
            result = authorize_risk(row, facts(positions=(position,)), policy(max_positions=3), NOW)
            self.assertFalse(result["allowed"])
        result = authorize_risk(candidate(symbol="MES"), facts(positions=(position,)), policy(max_positions=3, max_group_positions=3, max_open_risk=40, max_group_risk=40), NOW)
        self.assertFalse(result["allowed"])

    def test_loss_lock_unrealized_cooldown_and_limits(self):
        for state in (facts(loss_locked=True), facts(realized=-500), facts(realized=-490, unrealized=-11),
                      facts(daily_trades=20), facts(consecutive_losses=3), facts(last_closed_at=NOW)):
            self.assertFalse(authorize_risk(candidate(), state, policy(), NOW)["allowed"])

    def test_invalid_owner_protection_and_opposing(self):
        for changes in (dict(owner=""), dict(protected=False), dict(direction="SHORT")):
            base = dict(symbol="MES", contract_id="CON.F.US.MES.Z26", direction="LONG", quantity=1, entry=100., stop=90., strategy_id="crt", owner="a")
            base.update(changes)
            self.assertFalse(authorize_risk(candidate(), facts(positions=(Exposure(**base),)), policy(max_positions=3, max_group_positions=3), NOW)["allowed"])

    def test_gross_and_strategy_budget(self):
        self.assertFalse(authorize_risk(candidate(), facts(), policy(max_group_gross=100), NOW)["allowed"])
        self.assertFalse(authorize_risk(candidate(), facts(), policy(strategy_budgets=(("crt", 10),)), NOW)["allowed"])

    def test_protective_verification_is_not_assumed(self):
        exposure = Exposure("MES", "CON.F.US.MES.Z26", "LONG", 1, 100., 90., "crt", "owner")
        result = authorize_risk(candidate(), facts(positions=(exposure,)), policy(max_positions=3, max_group_positions=3), NOW)
        self.assertFalse(result["allowed"])
        self.assertIn("unprotected", result["reason"])
