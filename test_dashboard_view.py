import unittest
from dashboard_view import statistics


class DashboardTests(unittest.TestCase):
    def test_drawdown_is_chronological_and_includes_starting_zero(self):
        rows = [dict(time=3,net=-30,costs=1),dict(time=1,net=-10,costs=1),dict(time=2,net=20,costs=1)]
        stats = statistics(rows)
        self.assertEqual(stats["drawdown"],30)
        self.assertEqual(stats["net"],-20)
        self.assertEqual(stats["profit_factor"],.5)
        self.assertEqual(stats["costs"],3)

    def test_empty_stats_not_fake_win_rate(self):
        self.assertIsNone(statistics([])["win_rate"])
        self.assertIsNone(statistics([])["profit_factor"])
