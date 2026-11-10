"""Job orchestrator: create the job, fan out, wait for it to settle."""

from ..api.schemas import build_job
from ..config import settings
from ..storage import repo_jobs
from . import completion, dispatcher


def start(db, job):
    repo_jobs.create(db, job)
    dispatcher.fan_out(db, job)
    return job


def wait(db, job_id):
    sched = settings.section("scheduler")
    return completion.wait_for_settle(
        db, job_id, sched.get("completion_timeout_s", 20.0), sched.get("poll_interval_s", 0.02)
    )


def start_and_wait(db, job):
    start(db, job)
    return wait(db, job.job_id)


def run_job(db, job_id, total_pages, scale=48, sheet_size="ARCH_D"):
    """Fan out over every page of a job and wait for it to finish.

    Returns the final job row. ``status`` is 'complete' if every page reached
    a terminal state, 'stuck' if the job did not settle in time."""
    job = build_job(job_id, total_pages, scale, sheet_size)
    return start_and_wait(db, job)
