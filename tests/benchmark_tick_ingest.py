"""Opt-in local burst integrity/latency fixture; never a broker-speed guarantee."""
from contextlib import closing
from pathlib import Path
from threading import Event
import json
import statistics
import tempfile
import time
from unittest.mock import patch
from goxtrade.data import live_store, tick_buffer


def run():
    count=10000
    enqueued={}
    samples=[]
    write=tick_buffer.write_batch
    def measured_write(events):
        write(events)
        committed=time.perf_counter()
        samples.extend((committed-enqueued[event[3]['volume']])*1000 for event in events)
    with tempfile.TemporaryDirectory() as folder, patch.object(live_store,'DB_PATH',Path(folder)/'burst.db'):
        with closing(live_store.connect()) as conn:
            conn.execute('PRAGMA journal_mode=WAL')
        disconnected=Event()
        buffer=tick_buffer.TickBuffer(disconnected)
        began=time.perf_counter()
        for sequence in range(count):
            enqueued[sequence+1]=time.perf_counter()
            assert buffer.add('trade','MNQ=F','fixture',dict(price=30000+sequence*.25,volume=sequence+1))
        with patch.object(tick_buffer,'write_batch',side_effect=measured_write):
            buffer.start()
            buffer.close()
        duration=time.perf_counter()-began
        with closing(live_store.connect()) as conn:
            rows=conn.execute('SELECT price,volume FROM live_ticks ORDER BY id').fetchall()
        assert len(rows)==count
        assert all(row['price']==30000+index*.25 and row['volume']==index+1 for index,row in enumerate(rows))
        assert not disconnected.is_set() and buffer.gap_at is None
    samples.sort()
    report=dict(scope='ISOLATED LOCAL SYNTHETIC BURST; not exchange completeness, broker fills or live latency',
                events=count,committed=len(rows),missing=0,reordered=0,overflow=False,
                total_seconds=round(duration,4),events_per_second=round(count/duration),
                enqueue_to_commit_p50_ms=round(statistics.median(samples),2),
                enqueue_to_commit_p95_ms=round(samples[int(.95*(len(samples)-1))],2),
                enqueue_to_commit_max_ms=round(max(samples),2),orders_submitted=0)
    output=Path('data/verification/tick-ingest-benchmark.json')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    run()
