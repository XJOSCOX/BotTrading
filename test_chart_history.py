import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import live_store
from chart_history import chart_history
from tv_lightweight_chart import candle_points_from_ticks


class ChartHistoryTests(unittest.TestCase):
    def test_full_window_and_incremental_candles(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(live_store, 'DB_PATH', Path(folder) / 'test.db'):
                now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
                rows = []
                for hours, price in [(49, 90), (47, 100), (25, 110)]:
                    stamp = (now - timedelta(hours=hours)).isoformat()
                    rows.append(('TEST', 'test', 'trade', price, stamp, stamp))
                rows.extend([('TEST', 'test', 'trade', 120, now.isoformat(), now.isoformat())] * 50001)
                with live_store.connect() as conn:
                    conn.executemany('INSERT INTO live_ticks (symbol,contract_id,event_type,price,event_time,received_at) VALUES (?,?,?,?,?,?)', rows)
                conn.close()
                bars = chart_history('TEST')
                self.assertEqual(bars['open'].tolist(), [100, 110, 120])
                self.assertEqual(len(chart_history('TEST', 24)), 1)
                stamp = (now + timedelta(seconds=10)).isoformat()
                with live_store.connect() as conn:
                    conn.execute('INSERT INTO live_ticks (symbol,contract_id,event_type,price,event_time,received_at) VALUES (?,?,?,?,?,?)', ('TEST','test','trade',125,stamp,stamp))
                conn.close()
                bars = chart_history('TEST')
                self.assertEqual(bars.iloc[-1]['open'], 120)
                self.assertEqual(bars.iloc[-1]['close'], 125)
                self.assertEqual(candle_points_from_ticks(bars)[-1]['high'], 125)
                self.assertEqual(len(chart_history('TEST')), 3)


if __name__ == '__main__':
    unittest.main()
