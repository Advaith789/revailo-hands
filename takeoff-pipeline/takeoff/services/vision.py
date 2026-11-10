"""Client for the internal vision service.

The real service is a shared, account-wide resource. It accepts at most
MAX_CONCURRENT in-flight requests across every caller, every job and every
environment, and rejects anything above that with Throttled (HTTP 429).
"""

import hashlib
import random
import threading
import time

MAX_CONCURRENT = 10


class Throttled(Exception):
    """The vision service returned 429."""


class _VisionService:
    """Stands in for the remote service. Do not modify: this models the
    behaviour of a dependency we do not own."""

    def __init__(self):
        self._lock = threading.Lock()
        self._in_flight = 0
        self.peak_in_flight = 0
        self.throttled_count = 0

    def analyze(self, page_bytes):
        with self._lock:
            if self._in_flight >= MAX_CONCURRENT:
                self.throttled_count += 1
                raise Throttled("429 Too Many Requests")
            self._in_flight += 1
            self.peak_in_flight = max(self.peak_in_flight, self._in_flight)
        try:
            time.sleep(random.uniform(0.001, 0.004))
            if random.random() < 0.02:
                raise TimeoutError("vision service timed out")
            # A given page has one correct result. Latency and availability
            # vary, but a retry must not change the underlying measurement.
            digest = hashlib.blake2b(page_bytes, digest_size=8).digest()
            cents = int.from_bytes(digest, "big") % 39001
            return {"area_sqft": 10.0 + cents / 100}
        finally:
            with self._lock:
                self._in_flight -= 1

    def reset_counters(self):
        with self._lock:
            self.peak_in_flight = 0
            self.throttled_count = 0


SERVICE = _VisionService()


def analyze_page(page_bytes):
    return SERVICE.analyze(page_bytes)
