"""Completion.

The job row is the source of truth for the dashboard. A job settles when
its counters say every page is accounted for; if that does not happen
within the completion timeout the job is marked stuck for the on-call to
look at.
"""

import time

from ..storage import repo_jobs


def is_settled(row):
    """Every page has reached a terminal state: measured or failed.

    Failed pages count. Every set with 97 or more pages contains an
    unrenderable page, so ``pages_done`` alone can never reach
    ``total_pages`` for them. Equality (not >=) is deliberate: the counters
    are exact, and an overcount should surface as 'stuck', not as a job
    declared complete early.
    """
    return row["pages_done"] + row["pages_failed"] == row["total_pages"]


def wait_for_settle(db, job_id, timeout_s, poll_s):
    deadline = time.monotonic() + float(timeout_s)
    while time.monotonic() < deadline:
        row = repo_jobs.get(db, job_id)
        if is_settled(row):
            repo_jobs.set_status(db, job_id, "complete")
            return repo_jobs.get(db, job_id)
        time.sleep(float(poll_s))
    repo_jobs.set_status(db, job_id, "stuck")
    return repo_jobs.get(db, job_id)
