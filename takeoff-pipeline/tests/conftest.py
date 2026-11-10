import random

import pytest

from takeoff.cache import memo
from takeoff.services import metrics, vision
from takeoff.storage.db import Database


@pytest.fixture(autouse=True)
def _clean_process_state():
    random.seed(1234)
    memo.clear()
    metrics.reset()
    vision.SERVICE.reset_counters()
    yield
    memo.clear()
    metrics.reset()


@pytest.fixture
def db():
    database = Database()
    yield database
    database.close()
