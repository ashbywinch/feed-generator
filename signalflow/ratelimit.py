"""Thread-safe global pacing for external APIs.

All workers contend on ONE limiter per API, so parallelism can never burst
past a quota. wait() sleeps holding the lock so the next slot is booked
before any other thread can grab it; penalty() postpones after a 429.
"""

from __future__ import annotations

import threading
import time


class RateLimiter:
    def __init__(self, interval: float) -> None:
        self._interval = interval
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            if self._next_at > now:
                time.sleep(self._next_at - now)
                now = time.monotonic()
            self._next_at = now + self._interval

    def penalty(self, seconds: float) -> None:
        with self._lock:
            self._next_at = max(self._next_at, time.monotonic() + seconds)
