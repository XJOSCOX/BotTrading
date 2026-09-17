import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import closing

import live_store
from signal_lifecycle import track_signal, alert_history


class AlertHistoryTests(unittest.TestCase):
    def test_adaptive_history_survives_target_then_records_stop(self):
        from adaptive_exit import MODE
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store, 'DB_PATH', Path(folder)/'test.db'):
            signal = dict(signal='LONG',entry=100,stop=95,target=110,last_close=100,
                          exit_mode=MODE,tick_size=.25)
            def tick(price):
                with closing(live_store.connect()) as conn:
                    conn.execute("INSERT INTO live_ticks (symbol,contract_id,event_type,price,event_time,received_at) VALUES ('TEST','test','trade',?,?,?)",
                                 (price,live_store.utc_now(),live_store.utc_now()))
                    conn.commit()
            tick(100)
            track_signal('TEST','CRT',signal,'a',True)
            tick(111)
            track_signal('TEST','CRT',signal,'a',True)
            history = alert_history()
            self.assertEqual(history[0]['status'],'Active')
            self.assertTrue(history[0]['target_reached'])
            self.assertEqual(history[0]['initial_stop'],95)
            tick(94)
            track_signal('TEST','CRT',signal,'a',True)
            track_signal('TEST','CRT',signal,'a',True)
            history = alert_history()
            self.assertEqual(len(history),1)
            self.assertEqual(history[0]['status'],'Closed')
            self.assertEqual(history[0]['exit_reason'],'Stop reached')
            self.assertEqual(history[0]['exit_mode'],MODE)

    def test_entry_exit_and_no_duplicate(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store, 'DB_PATH', Path(folder)/'test.db'):
            def tick(price):
                with closing(live_store.connect()) as conn:
                    conn.execute("INSERT INTO live_ticks (symbol,contract_id,event_type,price,event_time,received_at) VALUES ('TEST','test','trade',?,'2026-09-17T03:00:00+00:00','2026-09-17T03:00:00+00:00')", (price,))
                    conn.commit()
            signal = dict(signal='LONG',entry=100,stop=95,target=110,last_close=100)
            tick(100)
            track_signal('TEST','CRT',signal,'a',True)
            self.assertEqual(alert_history()[0]['status'],'Active')
            tick(111)
            track_signal('TEST','CRT',signal,'a',True)
            track_signal('TEST','CRT',signal,'a',True)
            history = alert_history()
            self.assertEqual(len(history),1)
            self.assertEqual(history[0]['status'],'Closed')
            self.assertEqual(history[0]['exit_price'],111)
            self.assertEqual(history[0]['exit_reason'],'Target reached')


if __name__ == '__main__':
    unittest.main()
