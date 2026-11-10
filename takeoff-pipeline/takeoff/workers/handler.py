"""Invocation boundary.

In production every page is one Lambda invocation. This wraps
``process_page`` the way the Lambda handler does: build the context, stamp
it with the invocation id CloudWatch shows as RequestId, run.
"""

from ..core import ids
from ..core.models import PageContext
from ..util.logging import get_logger
from . import page_worker

log = get_logger("handler")


def invoke(db, job, page_no, attempt, gate):
    ctx = PageContext(
        job=job,
        page_no=page_no,
        attempt=attempt,
        invocation_id=ids.new_invocation_id(),
        gate=gate,
    )
    log.debug("invoke %s page=%s attempt=%s rid=%s", job.job_id, page_no, attempt, ctx.invocation_id)
    return page_worker.process_page(db, ctx)


def lambda_handler(event, context, db):
    """Entry point shape used by the deployed function."""
    from ..api.schemas import build_job

    job = build_job(
        event["job_id"], int(event["total_pages"]), int(event.get("scale", 48)),
        event.get("sheet_size", "ARCH_D"),
    )
    measurement = invoke(db, job, int(event["page_no"]), int(event.get("attempt", 1)), event.get("gate"))
    return {"job_id": job.job_id, "page_no": int(event["page_no"]), "area_sqft": measurement.area_sqft}
