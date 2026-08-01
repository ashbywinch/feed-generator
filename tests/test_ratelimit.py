"""Rate limiter: global pacing cannot be burst past, penalty postpones."""

import time

from signalflow.ratelimit import RateLimiter


def test_min_interval_between_waiters():
    rl = RateLimiter(0.2)
    rl.wait()  # first call: immediate
    t0 = time.monotonic()
    rl.wait()
    t1 = time.monotonic()
    assert t1 - t0 >= 0.19  # second slot is interval-spaced, not immediate


def test_penalty_postpones_next_slot():
    rl = RateLimiter(0.05)
    rl.penalty(0.3)
    t0 = time.monotonic()
    rl.wait()
    assert time.monotonic() - t0 >= 0.29


def test_parallel_waiters_stay_paced():
    """Two threads contending on one limiter never fire within the interval."""
    import threading

    rl = RateLimiter(0.15)
    stamps: list[float] = []
    lock = threading.Lock()

    def worker() -> None:
        rl.wait()
        with lock:
            stamps.append(time.monotonic())

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    stamps.sort()
    assert len(stamps) == 4
    gaps = [b - a for a, b in zip(stamps, stamps[1:], strict=False)]
    assert all(g >= 0.14 for g in gaps)
