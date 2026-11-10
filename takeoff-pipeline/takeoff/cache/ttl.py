import threading
import time


class TTLCache(object):
    """Small time-bounded cache keyed by hashable values."""

    def __init__(self, ttl_s, clock=time.monotonic):
        self.ttl_s = float(ttl_s)
        self._clock = clock
        self._lock = threading.Lock()
        self._items = {}

    def get(self, key):
        now = self._clock()
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            expires_at, value = item
            if now >= expires_at:
                del self._items[key]
                return None
            return value

    def put(self, key, value):
        with self._lock:
            self._items[key] = (self._clock() + self.ttl_s, value)

    def invalidate(self, key):
        with self._lock:
            self._items.pop(key, None)

    def clear(self):
        with self._lock:
            self._items.clear()

    def __len__(self):
        with self._lock:
            return len(self._items)
