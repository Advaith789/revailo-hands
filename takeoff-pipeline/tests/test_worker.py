from unittest.mock import patch

import pytest

from takeoff.api.schemas import build_job
from takeoff.core.errors import RenderError
from takeoff.core.models import PageContext
from takeoff.services import limiter
from takeoff.storage import repo_jobs, repo_results
from takeoff.workers import handler, render
from takeoff.workers.page_worker import process_page


def _ctx(job, page_no, attempt=1, rid="rid-1"):
    return PageContext(job=job, page_no=page_no, attempt=attempt, invocation_id=rid, gate=limiter.local(4))


def test_single_page_produces_a_result(db):
    job = build_job("w-1", 1)
    repo_jobs.create(db, job)
    with patch("takeoff.workers.page_worker.progress.publish"):
        measurement = process_page(db, _ctx(job, 1))
    assert measurement.area_sqft > 0
    assert len(repo_results.rows(db, "w-1")) == 1
    assert repo_jobs.get(db, "w-1")["pages_done"] == 1


def test_corrupt_page_is_rejected(db):
    job = build_job("w-2", 100)
    repo_jobs.create(db, job)
    with pytest.raises(RenderError):
        process_page(db, _ctx(job, 97))


def test_render_is_stable_for_the_same_page():
    job = build_job("w-3", 10)
    assert render.render_page(job, 4).data == render.render_page(job, 4).data


def test_receipts_are_unique_per_invocation():
    """Two deliveries of the same page must not collide in the results
    table, otherwise the second delivery is silently dropped."""
    job = build_job("w-4", 10)
    a = _ctx(job, 5, attempt=1, rid="aaa").receipt
    b = _ctx(job, 5, attempt=2, rid="bbb").receipt
    assert a != b
    assert len(a) == 24


def test_handler_builds_a_context_with_a_request_id(db):
    job = build_job("w-5", 2)
    repo_jobs.create(db, job)
    with patch("takeoff.workers.page_worker.progress.publish"):
        measurement = handler.invoke(db, job, 2, 1, limiter.local(2))
    assert measurement.area_sqft > 0
