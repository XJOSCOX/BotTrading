import unittest
import pandas as pd
from tv_lightweight_chart import candle_points_from_ticks


class CandleIntervalTests(unittest.TestCase):
    def test_intervals_preserve_ohlc(self):
        data = pd.DataFrame({'time': pd.date_range('2026-09-16T22:00:00Z', periods=60, freq='min'),
                             'open': range(60), 'high': range(2,62), 'low': range(-1,59), 'close': range(1,61), 'volume': [10]*60})
        for interval, size in [('1min',1),('5min',5),('15min',15),('30min',30),('1h',60)]:
            with self.subTest(interval=interval):
                points = candle_points_from_ticks(data, interval)
                self.assertEqual(len(points), 60//size)
                self.assertEqual(points[0]['open'], 0)
                self.assertEqual(points[0]['high'], size+1)
                self.assertEqual(points[0]['low'], -1)
                self.assertEqual(points[0]['close'], size)
                self.assertEqual(points[0]['volume'], 10*size)
                partial = candle_points_from_ticks(data.iloc[:7], interval)
                self.assertEqual(partial[-1]['close'], 7)

    def test_quotes_do_not_inflate_volume(self):
        frame = pd.DataFrame({'time': pd.to_datetime(['2026-09-16T22:00:00Z']*3),
                              'price':[100,101,102], 'volume':[100000,3,4], 'event_type':['quote','trade','trade']})
        self.assertEqual(candle_points_from_ticks(frame,'5min')[0]['volume'],7)


if __name__ == '__main__':
    unittest.main()
