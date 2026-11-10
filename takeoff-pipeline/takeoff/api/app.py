"""Request handlers.

No web framework: the deployed service is API Gateway in front of a Lambda
whose handler calls these functions with the decoded body, and the local
tests call them the same way.
"""

import threading

from ..cache.ttl import TTLCache
from ..config import flags, settings
from ..core.errors import NotFound
from ..reporting import totals
from ..scheduler import dispatcher, legacy_runner, orchestrator
from ..storage import repo_jobs
from ..util.logging import get_logger
from . import schemas, serializers

log = get_logger("api")

_status_cache = TTLCache(settings.cache.status_ttl_s)
_runs = {}
_runs_lock = threading.Lock()


def _run(db, job):
    if flags.LEGACY_RUNNER:
        legacy_runner.start_and_wait(db, job, create=False)
        return
    dispatcher.fan_out(db, job)
    orchestrator.wait(db, job.job_id)


def submit_job(db, payload):
    """POST /jobs"""
    req = schemas.parse_submit(payload)
    job = schemas.build_job(req.job_id, req.total_pages, req.scale, req.sheet_size)
    if repo_jobs.exists(db, job.job_id):
        return serializers.job_row(repo_jobs.get(db, job.job_id))

    # Create the row synchronously so the caller can poll immediately.
    repo_jobs.create(db, job)
    done = threading.Event()
    with _runs_lock:
        _runs[job.job_id] = done

    def target():
        try:
            _run(db, job)
        except Exception:  # pragma: no cover - surfaced via job status
            log.exception("job %s crashed", job.job_id)
        finally:
            done.set()

    threading.Thread(target=target, name="job-" + job.job_id, daemon=True).start()
    return serializers.job_row(repo_jobs.get(db, job.job_id))


def get_job(db, job_id):
    """GET /jobs/{job_id}"""
    cached = _status_cache.get(job_id)
    if cached is not None:
        return cached
    row = repo_jobs.get(db, job_id)
    body = serializers.job_row(row)
    _status_cache.put(job_id, body)
    return body


def get_totals(db, job_id):
    """GET /jobs/{job_id}/totals"""
    row = repo_jobs.get(db, job_id)
    return serializers.totals_body(
        row, totals.job_total(db, job_id), totals.measured_pages(db, job_id)
    )


def wait(db, job_id, timeout_s=None):
    """Block until the job's run finishes. Test helper; the API itself never
    blocks."""
    with _runs_lock:
        done = _runs.get(job_id)
    if done is None:
        raise NotFound(job_id)
    if timeout_s is None:
        timeout_s = float(settings.scheduler.completion_timeout_s) + 5.0
    done.wait(timeout_s)
    _status_cache.invalidate(job_id)
    return get_job(db, job_id)
