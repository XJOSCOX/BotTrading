import unittest
from decimal import Decimal
from signal_pnl import dollars, dollar_summary, money


class SignalPnlTests(unittest.TestCase):
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
