"""Concurrency gates.

``Gate`` bounds how many callers are inside a block at once. ``shared`` hands
every caller that asks for the same name the same gate, which is how the
account-wide vision limit is modelled when several jobs run in one process.
Production uses a token table in DynamoDB for the same purpose.
"""

import threading


class Gate(object):
    def __init__(self, capacity, name="gate"):
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.capacity = int(capacity)
        self.name = name
        self._sem = threading.BoundedSemaphore(self.capacity)
        self._lock = threading.Lock()
        self._in_use = 0
        self.peak = 0

    def acquire(self, timeout=None):
        ok = self._sem.acquire(timeout=timeout)
        if ok:
            with self._lock:
                self._in_use += 1
                self.peak = max(self.peak, self._in_use)
        return ok

    def release(self):
        with self._lock:
            self._in_use -= 1
        self._sem.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()
        return False

    def __repr__(self):
        return "Gate({}, capacity={}, in_use={})".format(self.name, self.capacity, self._in_use)


_registry = {}
_registry_lock = threading.Lock()


def shared(name, capacity):
    """Return the process-wide gate registered under ``name``, creating it on
    first use. Capacity is fixed by the first caller."""
    with _registry_lock:
        gate = _registry.get(name)
        if gate is None:
            gate = Gate(capacity, name=name)
            _registry[name] = gate
        return gate


def local(capacity, name="local"):
    return Gate(capacity, name=name)


def reset_registry():
    with _registry_lock:
        _registry.clear()
