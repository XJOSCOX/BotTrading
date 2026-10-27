import unittest
from decimal import Decimal
from goxtrade.bot.signal_pnl import dollars, dollar_summary, money, watch_outcome


class SignalPnlTests(unittest.TestCase):
    def test_watch_outcomes_use_observed_exits_and_micro_values(self):
        for symbol, micro, multiplier in (("NQ=F", "MNQ", 2), ("ES=F", "MES", 5), ("YM=F", "MYM", .5), ("MNQ=F", "MNQ", 2)):
            for side, sign in (("LONG", 1), ("SHORT", -1)):
                for difference in (-2, 0, 2):
                    row = dict(status="Closed", symbol=symbol, signal=side, entry=100,
                               exit_price=100+difference, exit_time="2026-10-27T02:00:00Z")
                    points = difference*sign
                    result = watch_outcome(row)
                    self.assertEqual(result, dict(state="WIN" if points>0 else "LOSS" if points<0 else "BREAKEVEN",
                        points=points, gross_one_micro=points*multiplier, instrument=micro))

    def test_watch_outcomes_never_score_clears_broker_exits_or_missing_data(self):
        row = dict(status="Closed", symbol="NQ=F", signal="LONG", entry=100, exit_price=102, exit_time="2026-10-27T02:00:00Z")
        for update in (dict(exit_source="broker"), dict(exit_time=None), dict(exit_price=None),
                       dict(entry=float("nan")), dict(exit_price=float("inf")), dict(symbol="UNKNOWN"), dict(signal="WAIT")):
            self.assertEqual(watch_outcome({**row, **update}), dict(state="UNSCORED"))
        self.assertEqual(watch_outcome({**row, "status":"Active"}), dict(state="OPEN"))
        self.assertEqual(watch_outcome({**row, "status":"Dismissed"}), dict(state="DISMISSED"))
    def test_contract_multipliers_and_directions(self):
        for symbol, value in (("NQ=F",20), ("ES=F",50), ("YM=F",5)):
            for side, sign in (("LONG",1), ("SHORT",-1)):
                row = dict(symbol=symbol,signal=side,entry=100)
                self.assertEqual(dollars(row,102),Decimal(2*value*sign))
                self.assertEqual(dollars(row,99),Decimal(-value*sign))

    def test_aggregate_dollars_not_points_and_exclude_open(self):
        rows = [
            dict(status="Closed",symbol="NQ=F",signal="LONG",entry=100,exit_price=102),
            dict(status="Closed",symbol="ES=F",signal="SHORT",entry=100,exit_price=101),
            dict(status="Closed",symbol="YM=F",signal="SHORT",entry=100,exit_price=98),
            dict(status="Active",symbol="NQ=F",signal="LONG",entry=100,exit_price=200),
        ]
        self.assertEqual(dollar_summary(rows),dict(won=Decimal(50),lost=Decimal(-50),net=Decimal(0),missing=0))

    def test_missing_and_bad_values(self):
        for symbol, entry, exit_price in (("MNQ=F",100,101),("ES=F",None,101),("ES=F",100,None),("ES=F",100,float("nan"))):
            self.assertIsNone(dollars(dict(symbol=symbol,entry=entry,signal="LONG"),exit_price))
        self.assertEqual(money(None),"--")
        self.assertEqual(money(Decimal("-12.50")),"-$12.50")
        self.assertEqual(money(Decimal("0")),"$0.00")

    def test_tick_and_fractional_quote_precision(self):
        row = dict(symbol="ES=F",entry=100,signal="LONG")
        self.assertEqual(dollars(row,100.25),Decimal("12.50"))
        row["symbol"] = "NQ=F"
        self.assertEqual(dollars(row,100.125),Decimal("2.50"))


if __name__ == "__main__":
    unittest.main()
