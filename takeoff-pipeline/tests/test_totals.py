import pytest

from takeoff.api.schemas import build_job
from takeoff.reporting import totals
from takeoff.storage import repo_jobs, repo_results


def test_total_is_the_sum_of_stored_rows(db):
    repo_jobs.create(db, build_job("t-1", 3))
    repo_results.record(db, "a", "t-1", 1, 10.25)
    repo_results.record(db, "b", "t-1", 2, 20.5)
    repo_results.record(db, "c", "t-1", 3, 30.0)
    assert totals.job_total(db, "t-1") == pytest.approx(60.75)
    assert totals.measured_pages(db, "t-1") == 3
    assert totals.page_breakdown(db, "t-1") == [(1, 10.25), (2, 20.5), (3, 30.0)]


def test_empty_job_totals_zero(db):
    repo_jobs.create(db, build_job("t-2", 3))
    assert totals.job_total(db, "t-2") == 0.0
