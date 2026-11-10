import time


class Stopwatch(object):
    """Context manager measuring wall time with the monotonic clock."""

    def __init__(self):
        self.start = None
        self.elapsed = None

    def __enter__(self):
        self.start = time.monotonic()
        return self

    def __exit__(self, *exc):
        self.elapsed = time.monotonic() - self.start
        return False


def ms(seconds):
    return int(round(seconds * 1000.0))
