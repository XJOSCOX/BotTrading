import unittest
from goxtrade.strategies.previous_day_box_config import PreviousDayBoxConfig
from goxtrade.strategies.previous_day_box_sessions import previous_box, zone
from tests.previous_day_box_fixtures import NOW, CONTRACT, history


class BoxZoneTests(unittest.TestCase):
    def test_math_and_all_five_states(self):
        box=previous_box(history(),NOW,PreviousDayBoxConfig(),CONTRACT)
        self.assertEqual([box[k] for k in ("pdh","pdl","range","midpoint","buy_upper","sell_lower")],[200,100,100,150,125,175])
        self.assertEqual([zone(price,box) for price in (99,110,150,180,201)],["Below PDL","Discount","Neutral","Premium","Above PDH"])

    def test_research_zone_alternatives(self):
        for buy,sell in ((20,80),(25,75),(30,70)):
            config=PreviousDayBoxConfig(buy_percent=buy,sell_percent=sell)
            box=previous_box(history(),NOW,config,CONTRACT)
            self.assertEqual((box["buy_upper"],box["sell_lower"]),(100+buy,100+sell))

    def test_invalid_or_overlapping_zones_rejected(self):
        for buy,sell in ((80,20),(50,50),(0,100),(float("nan"),75)):
            with self.subTest(buy=buy,sell=sell),self.assertRaises(ValueError):
                PreviousDayBoxConfig.from_dict(dict(buy_percent=buy,sell_percent=sell))
