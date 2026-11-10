"""Fan-out.

In production this is a Step Functions distributed map; here it is a thread
pool with the same retry semantics so the pipeline can be exercised locally.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from ..config import flags, settings
from ..core import retry
from ..core.errors import PermanentError, TransientError
from ..services import limiter, metrics
from ..storage import repo_jobs, repo_pages
from ..util.logging import get_logger
from ..workers import handler
from . import backoff

log = get_logger("dispatcher")


def gate_for(job):
    """Concurrency gate the job's pages share while calling the vision
    service."""
    if flags.SHARED_GATE:
        return limiter.shared("vision", settings.vision.max_in_flight)
    return limiter.local(settings.scheduler.per_job_concurrency, name="job:" + job.job_id)


def run_page(db, job, page_no, gate, policy):
    last_error = None
    for attempt in retry.attempts(policy):
        try:
            handler.invoke(db, job, page_no, attempt, gate)
            return True
        except PermanentError as exc:
            last_error = exc
            break
        except TransientError as exc:
            last_error = exc
            metrics.incr("page.retry")
            time.sleep(backoff.delay(policy, attempt))
    log.info("page %s/%s failed: %s", job.job_id, page_no, last_error)
    repo_pages.set_status(db, job.job_id, page_no, "failed")
    repo_jobs.increment_failed(db, job.job_id)
    return False


def fan_out(db, job):
    """Submit every page of ``job`` to the pool. Returns the submitting
    thread; it exits once every page has reached a terminal state."""
    gate = gate_for(job)
    policy = retry.policy_from_settings()
    pool_size = int(settings.scheduler.pool_size)

    def submit_all():
        with ThreadPoolExecutor(max_workers=pool_size) as pool:
            for page_no in range(1, job.total_pages + 1):
                pool.submit(run_page, db, job, page_no, gate, policy)

    runner = threading.Thread(target=submit_all, name="fanout-" + job.job_id, daemon=True)
    runner.start()
    return runner
