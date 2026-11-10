"""Aggregates over stored results."""

from ..storage import repo_results


def job_total(db, job_id):
    """Total measured area for the job, in square feet."""
    return float(repo_results.sum_area(db, job_id))


def measured_pages(db, job_id):
    return int(repo_results.count(db, job_id))


def page_breakdown(db, job_id):
    return [(int(p), float(a)) for p, a in repo_results.rows(db, job_id)]
