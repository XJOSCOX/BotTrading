import unittest
from goxtrade.execution.strategy_manager import evaluate
from tests.manager_fixtures import NOW, candidate, facts, policy


class ArbitrationTests(unittest.TestCase):
    def test_same_direction_one_owner_stops_unchanged(self):
        a, b = candidate(), candidate("reversal", key="b", stop=95.)
        decisions = evaluate([b, a], facts(), policy(), NOW)
        self.assertEqual(sum(d.selected for d in decisions), 1)
        winner = next(d for d in decisions if d.selected)
        self.assertEqual(winner.strategy_id, "crt")
        self.assertEqual(winner.support, (b.candidate_id,))
        self.assertEqual(a.stop, 90.)

    def test_opposite_direction_all_modes_block(self):
        a, b = candidate(), candidate("reversal", "SHORT", key="b")
        for mode in ("conservative", "first_confirmed", "configured_priority"):
            result = evaluate([a, b], facts(), policy(mode=mode), NOW)
            self.assertTrue(all(d.eligibility == "CONFLICTED" for d in result))
            self.assertFalse(any(d.selected for d in result))

    def test_confirmation_not_alert_id_and_order_independent(self):
        a = candidate("crt", confirmed_at="2026-10-22T14:59:50+00:00")
        b = candidate("reversal", key="b", confirmed_at="2026-10-22T14:59:40+00:00")
        selected = evaluate([a, b], facts(), policy(mode="first_confirmed"), NOW)
        self.assertEqual(next(d.strategy_id for d in selected if d.selected), "reversal")
        self.assertEqual(selected, evaluate([b, a], facts(), policy(mode="first_confirmed"), NOW))

    def test_invalid_opposite_does_not_create_conflict(self):
        a, b = candidate(), candidate("reversal", "SHORT", key="b", stop=None)
        self.assertTrue(any(d.selected for d in evaluate([a, b], facts(), policy(), NOW)))

    def test_configured_priority_and_evidence_fail_closed(self):
        a, b = candidate(), candidate("reversal", key="b")
        order = ("reversal", "crt", "orb", "vwap_reclaim", "ema_pullback", "vwap_ema_cross", "previous_day_box")
        result = evaluate([a, b], facts(), policy(priority=order, mode="configured_priority"), NOW)
        self.assertEqual(next(d.strategy_id for d in result if d.selected), "reversal")
        self.assertFalse(evaluate([a], facts(), policy(mode="evidence_research"), NOW)[0].selected)
