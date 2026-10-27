"""Local thread notification measurements, not market-to-fill latency."""
from pathlib import Path
from threading import Event, Thread
import json
import statistics
import time
from goxtrade.runtime.event_wakeup import WakeSignal


def run():
    signal=WakeSignal()
    acknowledged=Event()
    samples=[]
    started=[0.]
    def consumer():
        version=0
        for _ in range(100):
            version=signal.wait(version,3)
            samples.append((time.perf_counter()-started[0])*1000)
            acknowledged.set()
    worker=Thread(target=consumer,daemon=True)
    worker.start()
    for _ in range(100):
        acknowledged.clear()
        started[0]=time.perf_counter()
        signal.notify()
        assert acknowledged.wait(3),'Notification consumer stalled'
    worker.join(3)
    assert not worker.is_alive()
    observed=signal.version()
    for _ in range(10000):signal.notify()
    assert signal.wait(observed,3)==observed+10000
    samples.sort()
    report=dict(scope='LOCAL THREAD FIXTURE; not provider, strategy computation, broker or fill latency',
                notifications=len(samples),p50_wakeup_ms=round(statistics.median(samples),3),
                p95_wakeup_ms=round(samples[94],3),max_wakeup_ms=round(max(samples),3),
                burst_notifications_coalesced=10000,orders_submitted=0)
    path=Path('data/verification/event-wakeup-benchmark.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':run()
