"""Keep disk I/O off the websocket callback; preserve every queued tick."""
from contextlib import closing
from datetime import datetime, timezone
from queue import Queue, Empty, Full
from threading import Event, Thread
import logging
import time
from live_store import connect, utc_now
from price_ticks import valid_price


def event_age(value, now=None):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return None
        return ((now or datetime.now(timezone.utc))-stamp).total_seconds()
    except (ValueError, TypeError):
        return None


def write_batch(events):
    ticks, quotes = [], {}
    for kind, symbol, contract, payload, received in events:
        price = valid_price(symbol, payload.get("lastPrice" if kind == "quote" else "price"))
        timestamp = payload.get("timestamp") or (payload.get("lastUpdated") if kind == "quote" else None)
        bid, ask = (payload.get("bestBid"),payload.get("bestAsk")) if kind == "quote" else (None,None)
        ticks.append((symbol,contract,kind,price,bid,ask,payload.get("volume"),timestamp,received))
        if kind == "quote":
            quotes[symbol] = (symbol,contract,price,bid,ask,payload.get("volume"),timestamp,received)
    with closing(connect()) as conn:
        conn.executemany("INSERT INTO live_ticks(symbol,contract_id,event_type,price,best_bid,best_ask,volume,event_time,received_at) VALUES(?,?,?,?,?,?,?,?,?)",ticks)
        conn.executemany("""INSERT INTO latest_quotes(symbol,contract_id,last_price,best_bid,best_ask,volume,event_time,received_at)
            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET contract_id=excluded.contract_id,
            last_price=excluded.last_price,best_bid=excluded.best_bid,best_ask=excluded.best_ask,
            volume=excluded.volume,event_time=excluded.event_time,received_at=excluded.received_at""",quotes.values())
        conn.commit()


class TickBuffer:
    def __init__(self, disconnected, capacity=20000):
        self.queue = Queue(maxsize=capacity)
        self.stopping = Event()
        self.disconnected = disconnected
        self.worker = Thread(target=self.run,name="tick-writer",daemon=True)

    def start(self):
        self.worker.start()

    def add(self, kind, symbol, contract, payload):
        try:
            self.queue.put_nowait((kind,symbol,contract,dict(payload),utc_now()))
            return True
        except Full:
            logging.error("Tick buffer full: feed gap detected; reconnecting")
            self.disconnected.set()
            return False

    def run(self):
        while not self.stopping.is_set() or not self.queue.empty():
            try:
                batch = [self.queue.get(timeout=.1)]
            except Empty:
                continue
            deadline = time.monotonic()+.05
            while len(batch) < 1000 and time.monotonic() < deadline:
                try:
                    batch.append(self.queue.get(timeout=max(.001,deadline-time.monotonic())))
                except Empty:
                    break
            try:
                write_batch(batch)
            except Exception as error:
                logging.error("Tick batch persistence failed (%s); feed gap requires review",type(error).__name__)
                self.disconnected.set()
                return

    def close(self):
        self.stopping.set()
        self.worker.join(timeout=35)
        if self.worker.is_alive():
            raise RuntimeError("Tick writer did not finish draining")
