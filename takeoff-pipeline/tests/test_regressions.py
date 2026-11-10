"""Regression tests for the "numbers feel off / slow some mornings" escalation.

Every test here fails against the code as received (git tag ``original``) and
passes after the fixes. Test names carry the defect id used in REPORT.md
(D1..D6), so ``pytest -k d1`` runs one claim. Run them against both trees
with ``scripts/before_after.sh``.

The tests only use functions that exist in both trees, so on the original
code they fail on an assertion rather than an ImportError.

Ground truth: the vision service is deterministic on page bytes ("a given
page has one correct result"), so the correct total for a set is the sum of
one direct, sequential, uncached call per renderable page. ``true_total``
computes that without going through the scheduler, worker, memo or store.
"""

import threading
import time
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from takeoff.api import app
from takeoff.api.schemas import build_job
from takeoff.cache import memo
from takeoff.config import flags, loader, settings, toml_lite
from takeoff.core.errors import ProgressPublishError
from takeoff.reporting import totals
from takeoff.scheduler import completion
from takeoff.scheduler.orchestrator import run_job
from takeoff.services import vision, vision_client
from takeoff.storage import repo_pages
from takeoff.storage.db import Database
from takeoff.workers import render

PUBLISH = "takeoff.workers.page_worker.progress.publish"
ANALYZE = "takeoff.workers.page_worker.vision_client.analyze"


# --------------------------------------------------------------------------- helpers


@pytest.fixture
def short_timeout(monkeypatch):
    """Cap the settle wait so a job that never settles costs 5 s, not 20 s."""
    monkeypatch.setitem(settings._data["scheduler"], "completion_timeout_s", 5.0)


def true_area(job, page_no):
    data = render.render_page(job, page_no).data
    while True:
        try:
            return vision.SERVICE.analyze(data)["area_sqft"]
        except TimeoutError:  # latency/availability vary; the number does not
            continue


def true_total(job):
    total = sum(
        true_area(job, p) for p in range(1, job.total_pages + 1) if p % render.CORRUPT_EVERY
    )
    vision.SERVICE.reset_counters()
    return total


class FailFirstPublish(object):
    """Progress publisher that fails the first publish for the given pages,
    the way the real topic fails ~4% of the time, but deterministically."""

    def __init__(self, pages):
        self._pending = set(pages)
        self._lock = threading.Lock()

    def __call__(self, job_id, page_no, pages_done, total_pages):
        with self._lock:
            if page_no in self._pending:
                self._pending.discard(page_no)
                raise ProgressPublishError("injected: progress topic unavailable")


def run_concurrently(db, specs):
    rows = {}

    def one(job_id, pages, scale, sheet):
        rows[job_id] = run_job(db, job_id, pages, scale=scale, sheet_size=sheet)

    threads = [threading.Thread(target=one, args=spec) for spec in specs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return rows


# --------------------------------------------------------------------------- D1


def test_d1_a_failed_progress_event_does_not_count_the_page_twice(db, short_timeout):
    job = build_job("d1", 10)
    expected = true_total(job)
    with patch(PUBLISH, FailFirstPublish({3, 7})):
        row = run_job(db, "d1", 10)
    assert totals.measured_pages(db, "d1") == 10
    assert row["pages_done"] == 10
    assert totals.job_total(db, "d1") == pytest.approx(expected)


# --------------------------------------------------------------------------- D2


def test_d2_job_with_an_unrenderable_page_settles_promptly(db, short_timeout):
    with patch(PUBLISH):
        started = time.monotonic()
        row = run_job(db, "d2", 100)  # page 97 is corrupt
        elapsed = time.monotonic() - started
    assert row["status"] == "complete"
    assert (row["pages_done"], row["pages_failed"]) == (99, 1)
    assert elapsed < 4.0


def test_d2_settled_accounts_for_failed_pages():
    assert completion.is_settled({"pages_done": 99, "pages_failed": 1, "total_pages": 100})
    assert not completion.is_settled({"pages_done": 98, "pages_failed": 1, "total_pages": 100})


def test_d2_a_job_is_never_reported_complete_with_pages_outstanding(short_timeout):
    """Page 1's progress event fails (so it is delivered twice) while page 10
    is slow at the vision service. The job must not be called complete until
    page 10 is in.

    Uses its own Database and never closes it: on the original code page 10
    is still writing when run_job returns, and closing the connection under
    it crashed the interpreter (see REPORT.md, D7).
    """
    db = Database()
    release = threading.Event()
    real_analyze = vision_client.analyze

    def slow_page_10(page, gate):
        if page.page_no == 10:
            release.wait(5.0)
        return real_analyze(page, gate)

    threading.Timer(1.0, release.set).start()
    with patch(PUBLISH, FailFirstPublish({1})), patch(ANALYZE, side_effect=slow_page_10):
        row = run_job(db, "d2-early", 10)
        measured_at_completion = totals.measured_pages(db, "d2-early")
        pending_at_completion = repo_pages.count_by_status(db, "d2-early").get("pending", 0)
    release.set()
    assert row["status"] == "complete"
    assert pending_at_completion == 0
    assert measured_at_completion == 10


# --------------------------------------------------------------------------- D3


def test_d3_memo_key_differs_when_the_drawing_scale_differs():
    a = build_job("d3-a", 10, scale=48)
    b = build_job("d3-b", 10, scale=96)
    assert memo.key_for(a, render.render_page(a, 3)) != memo.key_for(b, render.render_page(b, 3))


def test_d3_resubmitting_a_set_at_a_new_scale_gets_new_measurements(db):
    corrected = build_job("d3-96", 6, scale=96)
    expected = true_total(corrected)
    with patch(PUBLISH):
        run_job(db, "d3-48", 6, scale=48)  # estimator picked the wrong scale...
        run_job(db, "d3-96", 6, scale=96)  # ...and re-runs it with the right one
    assert totals.job_total(db, "d3-96") == pytest.approx(expected)


# --------------------------------------------------------------------------- D4


def test_d4_flags_in_shipped_settings_are_in_the_flags_section():
    shipped = toml_lite.load(loader.default_settings_path())
    known = set(flags.snapshot())
    misplaced = sorted(
        "[{}] {}".format(section, key)
        for section, values in shipped.items()
        if section != "flags"
        for key in values
        if key in known
    )
    assert misplaced == []


def test_d4_shared_vision_gate_is_on_with_shipped_settings():
    assert flags.SHARED_GATE is True


def test_d4_concurrent_jobs_stay_under_the_account_wide_vision_limit(short_timeout):
    db = Database()
    vision.SERVICE.reset_counters()
    with patch(PUBLISH):
        rows = run_concurrently(db, [("d4-%d" % i, 40, 48, "ARCH_D") for i in range(4)])
    assert all(r["status"] == "complete" for r in rows.values())
    assert vision.SERVICE.throttled_count == 0
    assert vision.SERVICE.peak_in_flight <= vision.MAX_CONCURRENT


# --------------------------------------------------------------------------- D5


def test_d5_every_page_of_a_full_size_set_is_a_distinct_drawing():
    job = build_job("d5", 500)
    pages = [p for p in range(1, 501) if p % render.CORRUPT_EVERY]
    labels = [render.sheet_label(p) for p in pages]
    data = [render.render_page(job, p).data for p in pages]
    assert len(set(labels)) == len(labels)
    assert len(set(data)) == len(data)


def test_d5_sheet_labels_match_the_documented_examples():
    assert render.sheet_label(1) == "A-01"
    assert render.sheet_label(150) == "B-51"


# --------------------------------------------------------------------------- D6


def test_d6_api_timestamps_are_actually_utc(db):
    with patch(PUBLISH):
        body = app.submit_job(db, {"job_id": "d6", "total_pages": 2})
        app.wait(db, "d6")
    created = datetime.strptime(body["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    skew_s = abs((created - datetime.now(timezone.utc)).total_seconds())
    assert skew_s < 120


# --------------------------------------------------------------------------- end to end


def test_e2e_concurrent_mixed_jobs_match_ground_truth(short_timeout):
    """Customer-shaped morning: several large sets at once, one of them a
    re-run at a corrected scale, real (random) progress failures, real vision
    timeouts. Every total must equal the ground truth to the cent."""
    specs = [
        ("e2e-1", 250, 48, "ARCH_D"),
        ("e2e-2", 250, 96, "ARCH_D"),  # same set, corrected scale
        ("e2e-3", 120, 48, "ARCH_E"),
        ("e2e-4", 180, 24, "ARCH_C"),
    ]
    expected = {s[0]: true_total(build_job(*s)) for s in specs}
    db = Database()
    rows = run_concurrently(db, specs)
    for job_id, pages, _, _ in specs:
        row = rows[job_id]
        corrupt = pages // render.CORRUPT_EVERY
        assert row["status"] == "complete", job_id
        assert (row["pages_done"], row["pages_failed"]) == (pages - corrupt, corrupt), job_id
        assert totals.measured_pages(db, job_id) == pages - corrupt, job_id
        assert totals.job_total(db, job_id) == pytest.approx(expected[job_id]), job_id
    assert vision.SERVICE.throttled_count == 0


# --------------------------------------------------------------------------- D7


def test_d7_closing_the_database_waits_for_an_in_flight_write():
    db = Database()
    db.execute("CREATE TABLE t (x INTEGER)")
    closed = []

    with db.tx() as cur:  # hold the connection like a page worker mid-write
        cur.execute("INSERT INTO t VALUES (1)")
        closer = threading.Thread(target=lambda: (db.close(), closed.append(True)))
        closer.start()
        closer.join(0.3)
        closed_while_writing = bool(closed)
    closer.join(2.0)
    assert closed_while_writing is False
    assert closed == [True]


# --------------------------------------------------------------------------- D8


def test_d8_lambda_handler_works_with_a_json_only_event(db):
    """A deployed invocation receives a decoded JSON event: no gate object."""
    from takeoff.storage import repo_jobs
    from takeoff.workers import handler

    repo_jobs.create(db, build_job("d8", 3))
    with patch(PUBLISH):
        out = handler.lambda_handler({"job_id": "d8", "total_pages": 3, "page_no": 2}, None, db)
    assert out["page_no"] == 2 and out["area_sqft"] > 0
    assert totals.measured_pages(db, "d8") == 1
