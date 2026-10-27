"""Process-local, coalesced wakeups. Events schedule work; never authorize orders."""
import time
from threading import Condition


class WakeSignal:
    def __init__(self):
        self.condition = Condition()
        self.generation = 0

    def version(self):
        with self.condition:
            return self.generation

    def notify(self):
        with self.condition:
            self.generation += 1
            self.condition.notify_all()

    def wait(self, after, timeout, *, not_before=0):
        deadline = time.monotonic() + max(0, timeout)
        with self.condition:
            while True:
                now = time.monotonic()
                changed = self.generation != after
                if now >= not_before and (changed or now >= deadline):
                    return self.generation
                target = not_before if changed or now >= deadline else deadline
                self.condition.wait(max(0, target-now))


MARKET_WAKE = WakeSignal()
EXECUTION_WAKE = WakeSignal()
