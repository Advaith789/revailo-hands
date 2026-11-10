from takeoff.api.schemas import build_job
from takeoff.cache import memo
from takeoff.cache.ttl import TTLCache
from takeoff.core.models import Measurement
from takeoff.workers import render


def test_ttl_cache_expires():
    now = [100.0]
    cache = TTLCache(ttl_s=1.0, clock=lambda: now[0])
    cache.put("k", "v")
    assert cache.get("k") == "v"
    now[0] += 1.5
    assert cache.get("k") is None


def test_memo_round_trip():
    job = build_job("c-1", 10)
    page = render.render_page(job, 3)
    key = memo.key_for(job, page)
    assert memo.get(key) is None
    memo.put(key, Measurement(42.0))
    assert memo.get(key).area_sqft == 42.0
    assert memo.stats() == {"hits": 1, "misses": 1, "size": 1}


def test_memo_key_is_stable_for_a_re_upload():
    first = build_job("c-2", 10)
    again = build_job("c-3", 10)
    page = render.render_page(first, 7)
    assert memo.key_for(first, page) == memo.key_for(again, page)
