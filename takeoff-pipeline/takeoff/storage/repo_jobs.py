from ..core import clock
from ..core.errors import NotFound

_COLUMNS = (
    "job_id", "total_pages", "pages_done", "pages_failed", "status",
    "scale", "sheet_size", "fingerprint", "created_at", "updated_at",
)


def _row(values):
    return dict(zip(_COLUMNS, values))


def create(db, job):
    now = clock.stamp()
    with db.tx() as cur:
        cur.execute(
            "INSERT INTO jobs (job_id, total_pages, scale, sheet_size, fingerprint, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (job.job_id, job.total_pages, job.scale, job.sheet_size, job.fingerprint, now, now),
        )
        cur.executemany(
            "INSERT INTO pages (job_id, page_no) VALUES (?, ?)",
            [(job.job_id, n) for n in range(1, job.total_pages + 1)],
        )


def get(db, job_id):
    values = db.query_one(
        "SELECT {} FROM jobs WHERE job_id = ?".format(", ".join(_COLUMNS)), (job_id,)
    )
    if values is None:
        raise NotFound(job_id)
    return _row(values)


def exists(db, job_id):
    return db.query_one("SELECT 1 FROM jobs WHERE job_id = ?", (job_id,)) is not None


def increment_done(db, job_id):
    """Advance the job's completed-page counter by one."""
    with db.tx() as cur:
        (current,) = cur.execute(
            "SELECT pages_done FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        cur.execute(
            "UPDATE jobs SET pages_done = ?, updated_at = ? WHERE job_id = ?",
            (current + 1, clock.stamp(), job_id),
        )


def increment_failed(db, job_id):
    with db.tx() as cur:
        (current,) = cur.execute(
            "SELECT pages_failed FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        cur.execute(
            "UPDATE jobs SET pages_failed = ?, updated_at = ? WHERE job_id = ?",
            (current + 1, clock.stamp(), job_id),
        )


def set_status(db, job_id, status):
    db.execute(
        "UPDATE jobs SET status = ?, updated_at = ? WHERE job_id = ?",
        (status, clock.stamp(), job_id),
    )


def list_by_status(db, status):
    rows = db.query(
        "SELECT {} FROM jobs WHERE status = ? ORDER BY created_at".format(", ".join(_COLUMNS)),
        (status,),
    )
    return [_row(r) for r in rows]


def record_page_failure(db, job_id, page_no):
    """Mark a page failed and count it, unless its result is already stored.

    A page can exhaust its retries after its result was stored (the store
    succeeded, a later step such as the progress event kept failing). That
    page is done, not failed: counting it as both would push
    ``pages_done + pages_failed`` past ``total_pages``. Returns True if the
    page was counted as failed.
    """
    with db.tx() as cur:
        stored = cur.execute(
            "SELECT 1 FROM results WHERE job_id = ? AND page_no = ?", (job_id, page_no)
        ).fetchone()
        if stored is not None:
            return False
        cur.execute(
            "UPDATE pages SET status = 'failed' WHERE job_id = ? AND page_no = ?",
            (job_id, page_no),
        )
        cur.execute(
            "UPDATE jobs SET pages_failed = pages_failed + 1, updated_at = ? WHERE job_id = ?",
            (clock.stamp(), job_id),
        )
        return True
