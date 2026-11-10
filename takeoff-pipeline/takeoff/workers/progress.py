"""Progress events. The dashboard subscribes to a topic (SNS in
production) and moves the bar on every event."""

import random

from ..config import flags
from ..core.errors import ProgressPublishError
from ..services import metrics

FAILURE_RATE = 0.04


def publish(job_id, page_no, pages_done, total_pages):
    if not flags.PROGRESS_EVENTS:
        return
    if random.random() < FAILURE_RATE:
        metrics.incr("progress.failed")
        raise ProgressPublishError("progress topic unavailable")
    metrics.incr("progress.published")
