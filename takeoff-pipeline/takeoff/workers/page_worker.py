"""Per-page worker.

One invocation handles one page: render it, measure it, store the result,
advance the job counter, publish a progress event, mark the page done.
Raises on any failure; the scheduler decides whether to retry.
"""

from ..cache import memo
from ..config import flags
from ..core import clock
from ..services import vision_client
from ..storage import repo_jobs, repo_pages, repo_results
from ..util.logging import get_logger
from . import progress, render

log = get_logger("worker")


def process_page(db, ctx):
    job = ctx.job
    repo_pages.bump_attempts(db, job.job_id, ctx.page_no)

    page = render.render_page(job, ctx.page_no)

    measurement = None
    key = None
    if flags.MEASUREMENT_CACHE:
        key = memo.key_for(job, page)
        measurement = memo.get(key)
    if measurement is None:
        measurement = vision_client.analyze(page, ctx.gate)
        if key is not None:
            memo.put(key, measurement)

    # Result, counter and page status move together; a redelivery of a page
    # that is already stored changes nothing.
    repo_results.record_and_advance(
        db, ctx.receipt, job.job_id, ctx.page_no, measurement.area_sqft, measurement.source,
        stamp=clock.stamp(),
    )

    # The progress event is published after the result is durable. If it
    # fails, the scheduler retries the page; that retry is now harmless.
    row = repo_jobs.get(db, job.job_id)
    progress.publish(job.job_id, ctx.page_no, row["pages_done"], row["total_pages"])

    log.debug("page %s/%s done (attempt %s)", job.job_id, ctx.page_no, ctx.attempt)
    return measurement
