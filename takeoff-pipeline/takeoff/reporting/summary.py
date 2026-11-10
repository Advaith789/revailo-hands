from ..cache import memo
from ..core import clock
from ..services import metrics
from . import totals


def render_summary(db, row):
    lines = [
        "job {}  status={}  pages={}  done={}  failed={}".format(
            row["job_id"], row["status"], row["total_pages"], row["pages_done"], row["pages_failed"]
        ),
        "total area: {:,.2f} sq ft over {} measured pages".format(
            totals.job_total(db, row["job_id"]), totals.measured_pages(db, row["job_id"])
        ),
        "memo: {}".format(memo.stats()),
        "counters: {}".format(metrics.snapshot()["counters"]),
        "as of {} ({})".format(clock.wall_now().strftime("%Y-%m-%d %H:%M:%S"), clock.REGION_TZ),
    ]
    return "\n".join(lines)
