"""Measurement memo.

The vision service bills per call and estimators re-upload the same sets
constantly (revisions, re-runs after a crash, "let me just check"). A page
that has already been measured for a set is served from here instead of
being billed again. Production backs this with a DynamoDB table with TTL;
locally it is a dict.
"""

import hashlib
import threading
import time

from ..config import settings
from .ttl import TTLCache

_lock = threading.Lock()
_cache = TTLCache(settings.cache.measurement_ttl_s)
_hits = 0
_misses = 0


# Bump when the meaning of a key changes, so entries written under the old
# scheme (still in the production table until their TTL) are never read.
KEY_VERSION = "v2"


def key_for(job, page):
    """Memo key for one page of a set.

    Keyed on the rendered bytes, which is exactly what the vision service's
    answer depends on ("the same bytes always produce the same number"). Two
    pages share a key if and only if they would get the same measurement, so
    a hit can never return another drawing's number, whatever changed
    between uploads (scale, sheet size, a revised drawing), while a genuine
    re-upload of the same set still hits. The previous key,
    ``fingerprint:page_no``, left the scale out of the fingerprint and served
    a set's old measurements after it was re-run at a corrected scale.
    """
    digest = hashlib.blake2b(page.data, digest_size=16).hexdigest()
    return "{}:{}".format(KEY_VERSION, digest)


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
