"""In-process counters and timers. Production ships these to CloudWatch
embedded metrics; here they are kept in memory for tests and the CLI."""

import threading
import time
from contextlib import contextmanager

_lock = threading.Lock()
_counters = {}
_timers = {}


def incr(name, by=1):
    with _lock:
        _counters[name] = _counters.get(name, 0) + by


def observe(name, seconds):
    with _lock:
        bucket = _timers.setdefault(name, {"count": 0, "total_s": 0.0, "max_s": 0.0})
        bucket["count"] += 1
        bucket["total_s"] += seconds
        bucket["max_s"] = max(bucket["max_s"], seconds)


@contextmanager
def timer(name):
    start = time.monotonic()
    try:
        yield
    finally:
        observe(name, time.monotonic() - start)


def counter(name):
    with _lock:
        return _counters.get(name, 0)


def snapshot():
    with _lock:
        return {"counters": dict(_counters), "timers": {k: dict(v) for k, v in _timers.items()}}


def reset():
    with _lock:
        _counters.clear()
        _timers.clear()
