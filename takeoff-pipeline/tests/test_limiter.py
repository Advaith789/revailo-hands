import threading
import time

from takeoff.services import limiter


def test_shared_returns_the_same_gate_for_the_same_name():
    limiter.reset_registry()
    a = limiter.shared("x", 3)
    b = limiter.shared("x", 99)
    assert a is b
    assert a.capacity == 3


def test_gate_bounds_concurrency():
    gate = limiter.local(3)

    def work():
        with gate:
            time.sleep(0.01)

    threads = [threading.Thread(target=work) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert gate.peak == 3
