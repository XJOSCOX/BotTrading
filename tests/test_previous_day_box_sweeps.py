import unittest
from goxtrade.strategies.previous_day_box import swept, confirmed_swing, evaluate_previous_day_box
from goxtrade.strategies.previous_day_box_config import PreviousDayBoxConfig
from tests.previous_day_box_fixtures import NOW, CONTRACT, history
import pandas as pd


class SweepTests(unittest.TestCase):
    def test_minimum_distance_and_completed_reclaim(self):
        box=dict(pdl=100,pdh=200,buy_upper=125,sell_lower=175)
        config=PreviousDayBoxConfig(min_sweep_ticks=2)
        self.assertTrue(swept(dict(low=99.5,close=101),box,"LONG",config,.25))
        self.assertFalse(swept(dict(low=99.75,close=101),box,"LONG",config,.25))
        self.assertFalse(swept(dict(low=99,close=99),box,"LONG",config,.25))
        self.assertTrue(swept(dict(high=200.5,close=199),box,"SHORT",config,.25))

    def test_outside_default_requires_reclaim_not_touch(self):
        frame=history()
        frame.loc[frame["time"]>=NOW-pd.Timedelta(minutes=15),["open","high","low","close"]]=[100.,101.,98.,99.]
        result,_=evaluate_previous_day_box(frame,99,NOW,contract_id=CONTRACT,quote_time=NOW)
        self.assertEqual(result["signal"],"WAIT")
        frame.loc[frame["time"]>=NOW-pd.Timedelta(minutes=15),["open","high","low","close"]]=[102.,104.,99.,103.]
        result,_=evaluate_previous_day_box(frame,103,NOW,dict(confirmation="sweep"),contract_id=CONTRACT,quote_time=NOW)
        self.assertEqual(result["signal"],"LONG",result["reason"])
        ignored,_=evaluate_previous_day_box(frame,103,NOW,dict(confirmation="sweep",outside_mode="ignore"),contract_id=CONTRACT,quote_time=NOW)
        self.assertEqual(ignored["signal"],"WAIT")

    def test_pivot_needs_right_hand_confirmation(self):
        frame=pd.DataFrame(dict(high=[100,105,102],low=[90,91,92]))
        self.assertIsNone(confirmed_swing(frame.iloc[:2],True,1))
        self.assertEqual(confirmed_swing(frame,True,1),105)
