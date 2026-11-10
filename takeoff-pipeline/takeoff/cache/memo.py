"""Measurement memo.

The vision service bills per call and estimators re-upload the same sets
constantly (revisions, re-runs after a crash, "let me just check"). A page
that has already been measured for a set is served from here instead of
being billed again. Production backs this with a DynamoDB table with TTL;
locally it is a dict.
"""

import threading
import time

from ..config import settings
from .ttl import TTLCache

_lock = threading.Lock()
_cache = TTLCache(settings.cache.measurement_ttl_s)
_hits = 0
_misses = 0


def key_for(job, page):
    """Memo key for one page of a set."""
    return "{}:{}".format(job.fingerprint, page.page_no)


def get(key):
    global _hits, _misses
    value = _cache.get(key)
    with _lock:
        if value is None:
            _misses += 1
        else:
            _hits += 1
    return value


def put(key, measurement):
    _cache.put(key, measurement)


def clear():
    global _hits, _misses
    _cache.clear()
    with _lock:
        _hits = 0
        _misses = 0


def stats():
    with _lock:
        return {"hits": _hits, "misses": _misses, "size": len(_cache)}


def _now():
    return time.monotonic()
