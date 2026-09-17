import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import live_store
from price_ticks import valid_price


class PriceTickTests(unittest.TestCase):
    def test_increments(self):
        self.assertEqual(valid_price("YM=F",52234),52234)
        self.assertIsNone(valid_price("YM=F",52234.5))
        for symbol in ("NQ=F","ES=F"):
            for value in (100,100.25,100.5,100.75):
                self.assertEqual(valid_price(symbol,value),value)
            self.assertIsNone(valid_price(symbol,100.125))

    def test_quote_without_last_does_not_invent_price(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store,"DB_PATH",Path(folder)/"test.db"):
            live_store.save_trade("NQ=F","test",dict(price=100.25))
            live_store.save_quote("NQ=F","test",dict(bestBid=100.25,bestAsk=100.5))
            self.assertEqual(live_store.latest_prices(["NQ=F"])["NQ=F"]["price"],100.25)
            live_store.save_trade("NQ=F","test",dict(price=100.375))
            self.assertEqual(len(live_store.ticks_for_symbol("NQ=F")),1)


if __name__ == "__main__":
    unittest.main()
