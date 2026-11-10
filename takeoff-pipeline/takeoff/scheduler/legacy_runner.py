"""Pre-dispatcher runner.

Superseded by dispatcher.py + completion.py in the flags rollout. Kept for
the rollback window (OPS-2291); selected only when ``flags.LEGACY_RUNNER``
is on. Do not extend.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from ..config import settings
from ..core.errors import PermanentError, TransientError
from ..services import vision
from ..storage import repo_jobs, repo_pages
from ..workers import handler

MAX_ATTEMPTS = 4
POOL_SIZE = 24


def _bump_done(db, job_id):
    current = db.query_one("SELECT pages_done FROM jobs WHERE job_id = ?", (job_id,))[0]
    db.execute("UPDATE jobs SET pages_done = ? WHERE job_id = ?", (current + 1, job_id))


def _run_page(db, job, page_no, gate):
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with gate:
                handler.invoke(db, job, page_no, attempt, _NullGate())
            return True
        except PermanentError:
            break
        except TransientError:
            time.sleep(0.01 * (2 ** (attempt - 1)))
    repo_pages.set_status(db, job.job_id, page_no, "failed")
    repo_jobs.increment_failed(db, job.job_id)
    return False


class _NullGate(object):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def start_and_wait(db, job, create=True):
    if create:
        repo_jobs.create(db, job)
    gate = threading.Semaphore(vision.MAX_CONCURRENT)

    def submit_all():
        with ThreadPoolExecutor(max_workers=POOL_SIZE) as pool:
            for page_no in range(1, job.total_pages + 1):
                pool.submit(_run_page, db, job, page_no, gate)

    threading.Thread(target=submit_all, daemon=True).start()

    deadline = time.time() + settings.scheduler.completion_timeout_s
    while time.time() < deadline:
        row = repo_jobs.get(db, job.job_id)
        if row["pages_done"] == row["total_pages"]:
            repo_jobs.set_status(db, job.job_id, "complete")
            return repo_jobs.get(db, job.job_id)
        time.sleep(0.02)
    repo_jobs.set_status(db, job.job_id, "stuck")
    return repo_jobs.get(db, job.job_id)
