import unittest
import tempfile
from pathlib import Path
from threading import Event
from unittest.mock import patch
from datetime import datetime,timezone
from contextlib import closing
import live_store
from tick_buffer import TickBuffer,write_batch,event_age


class TickBufferTests(unittest.TestCase):
    def test_batch_preserves_order_prices_volumes_and_event_times(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store,"DB_PATH",Path(folder)/"test.db"):
            write_batch([("trade","NQ=F","nq",dict(price=100.25,volume=3,timestamp="2026-09-17T12:00:00Z"),"2026-09-17T12:03:00Z"),
                         ("quote","NQ=F","nq",dict(lastPrice=100.5,volume=100),"2026-09-17T12:03:01Z"),
                         ("trade","NQ=F","nq",dict(price=100.125,volume=1),"2026-09-17T12:03:02Z")])
            with closing(live_store.connect()) as conn:
                rows = conn.execute("SELECT * FROM live_ticks ORDER BY id").fetchall()
            self.assertEqual(len(rows),3)
            self.assertEqual(rows[0]["volume"],3)
            self.assertEqual(rows[0]["event_time"],"2026-09-17T12:00:00Z")
            self.assertIsNone(rows[2]["price"])
            self.assertEqual(live_store.latest_prices(["NQ=F"])["NQ=F"]["price"],100.5)

    def test_drain_and_overflow(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store,"DB_PATH",Path(folder)/"test.db"):
            buffer = TickBuffer(Event())
            for n in range(200):
                buffer.add("trade","YM=F","ym",dict(price=50000+n,volume=1))
            buffer.start()
            buffer.close()
            with closing(live_store.connect()) as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM live_ticks").fetchone()[0],200)
            disconnected = Event()
            buffer = TickBuffer(disconnected,capacity=1)
            self.assertTrue(buffer.add("trade","YM=F","ym",{}))
            self.assertFalse(buffer.add("trade","YM=F","ym",{}))
            self.assertTrue(disconnected.is_set())

    def test_fresh_arrival_does_not_make_old_market_timestamp_fresh(self):
        now = datetime(2026,9,17,12,3,tzinfo=timezone.utc)
        self.assertEqual(event_age("2026-09-17T12:00:00Z",now),180)
        self.assertIsNone(event_age(None,now))
        self.assertIsNone(event_age("2026-09-17T12:00:00",now))
