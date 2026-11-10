from unittest.mock import patch

from takeoff.api.schemas import build_job
from takeoff.core.errors import RenderError, VisionUnavailable
from takeoff.core.models import Measurement
from takeoff.core.retry import RetryPolicy
from takeoff.scheduler import backoff, dispatcher
from takeoff.scheduler.orchestrator import run_job
from takeoff.services import limiter
from takeoff.storage import repo_jobs


def test_small_job_completes(db):
    # Keep this starter smoke test independent of transient dependency failures.
    with patch("takeoff.workers.page_worker.vision_client.analyze", return_value=Measurement(10.0)), patch(
        "takeoff.workers.page_worker.progress.publish"
    ):
        row = run_job(db, "s-1", 8)
    assert row["status"] == "complete"
    assert row["pages_done"] == 8


def test_backoff_grows_and_is_capped():
    policy = RetryPolicy(max_attempts=6, base_s=0.1, cap_s=0.5, jitter=False)
    delays = [backoff.delay(policy, a) for a in range(1, 7)]
    assert delays == [0.1, 0.2, 0.4, 0.5, 0.5, 0.5]


def test_permanent_errors_are_not_retried(db):
    job = build_job("s-2", 1)
    repo_jobs.create(db, job)
    policy = RetryPolicy(max_attempts=4, base_s=0.0, cap_s=0.0, jitter=False)
    with patch("takeoff.scheduler.dispatcher.handler.invoke", side_effect=RenderError("bad")) as invoke:
        ok = dispatcher.run_page(db, job, 1, limiter.local(1), policy)
    assert ok is False
    assert invoke.call_count == 1
    assert repo_jobs.get(db, "s-2")["pages_failed"] == 1


def test_transient_errors_are_retried_then_succeed(db):
    job = build_job("s-3", 1)
    repo_jobs.create(db, job)
    policy = RetryPolicy(max_attempts=4, base_s=0.0, cap_s=0.0, jitter=False)
    with patch(
        "takeoff.scheduler.dispatcher.handler.invoke",
        side_effect=[VisionUnavailable("429"), VisionUnavailable("429"), Measurement(1.0)],
    ) as invoke:
        ok = dispatcher.run_page(db, job, 1, limiter.local(1), policy)
    assert ok is True
    assert invoke.call_count == 3
