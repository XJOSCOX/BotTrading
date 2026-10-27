import unittest
import tempfile
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch
from datetime import datetime,timezone
from contextlib import closing
from goxtrade.data import live_store
from goxtrade.data.tick_buffer import TickBuffer, write_batch, event_age


class TickBufferTests(unittest.TestCase):
    def test_notification_occurs_only_after_data_is_committed(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store,'DB_PATH',Path(folder)/'notify.db'):
            observed=[]
            def committed():
                with closing(live_store.connect()) as conn:
                    observed.append(conn.execute('SELECT COUNT(*) FROM live_ticks').fetchone()[0])
            buffer=TickBuffer(Event(),on_commit=committed)
            buffer.add('trade','MNQ=F','fixture',dict(price=100.,volume=1))
            buffer.start();buffer.close()
            self.assertEqual(observed,[1])

    def test_persistence_failure_never_notifies_and_callback_failure_keeps_data(self):
        notify=Mock()
        buffer=TickBuffer(Event(),on_commit=notify)
        buffer.add('trade','MNQ=F','fixture',dict(price=100.))
        with patch('goxtrade.data.tick_buffer.write_batch',side_effect=RuntimeError('fixture disk failure')):
            buffer.start();buffer.close()
        notify.assert_not_called()
        self.assertIsNotNone(buffer.gap_at)
        with tempfile.TemporaryDirectory() as folder,patch.object(live_store,'DB_PATH',Path(folder)/'callback.db'):
            disconnected=Event()
            buffer=TickBuffer(disconnected,on_commit=Mock(side_effect=RuntimeError('fixture notification failure')))
            buffer.add('trade','MNQ=F','fixture',dict(price=100.))
            buffer.start();buffer.close()
            with closing(live_store.connect()) as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM live_ticks').fetchone()[0],1)
            self.assertFalse(disconnected.is_set())
            self.assertIsNone(buffer.gap_at)
    def test_ten_thousand_tick_burst_is_not_coalesced_or_reordered(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store,'DB_PATH',Path(folder)/'burst.db'):
            disconnected=Event()
            buffer=TickBuffer(disconnected)
            for sequence in range(10000):
                self.assertTrue(buffer.add('trade','MNQ=F','fixture',dict(price=30000+sequence*.25,volume=sequence+1)))
            buffer.start()
            buffer.close()
            with closing(live_store.connect()) as conn:
                rows=conn.execute('SELECT price,volume FROM live_ticks ORDER BY id').fetchall()
            self.assertEqual(len(rows),10000)
            self.assertEqual([(r['price'],r['volume']) for r in rows],[(30000+n*.25,n+1) for n in range(10000)])
            self.assertFalse(disconnected.is_set())
            self.assertIsNone(buffer.gap_at)

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
            self.assertIsNotNone(buffer.gap_at)

    def test_failed_batch_retains_earliest_lost_receipt(self):
        disconnected = Event()
        buffer = TickBuffer(disconnected)
        first = "2026-10-01T15:00:01+00:00"
        buffer.queue.put(("trade", "NQ=F", "nq", {}, first))
        buffer.queue.put(("trade", "NQ=F", "nq", {}, "2026-10-01T15:00:02+00:00"))
        with patch("goxtrade.data.tick_buffer.write_batch", side_effect=RuntimeError("disk unavailable")):
            buffer.start()
            buffer.worker.join(timeout=5)
        self.assertFalse(buffer.worker.is_alive())
        self.assertEqual(buffer.gap_at, first)
        self.assertTrue(disconnected.is_set())

    def test_fresh_arrival_does_not_make_old_market_timestamp_fresh(self):
        now = datetime(2026,9,17,12,3,tzinfo=timezone.utc)
        self.assertEqual(event_age("2026-09-17T12:00:00Z",now),180)
        self.assertIsNone(event_age(None,now))
        self.assertIsNone(event_age("2026-09-17T12:00:00",now))
