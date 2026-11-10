import sqlite3


def record(db, receipt, job_id, page_no, area_sqft, source="vision"):
    """Store a page result. Returns True if this call stored a new row,
    False if the receipt had already been recorded."""
    try:
        db.execute(
            "INSERT INTO results (receipt, job_id, page_no, area_sqft, source) "
            "VALUES (?, ?, ?, ?, ?)",
            (receipt, job_id, page_no, area_sqft, source),
        )
        return True
    except sqlite3.IntegrityError:
        return False


def rows(db, job_id):
    return db.query(
        "SELECT page_no, area_sqft FROM results WHERE job_id = ? ORDER BY page_no", (job_id,)
    )


def count(db, job_id):
    return db.query_one("SELECT COUNT(*) FROM results WHERE job_id = ?", (job_id,))[0]


def sum_area(db, job_id):
    return db.query_one(
        "SELECT COALESCE(SUM(area_sqft), 0) FROM results WHERE job_id = ?", (job_id,)
    )[0]


def record_and_advance(db, receipt, job_id, page_no, area_sqft, source="vision", stamp=""):
    """Store a page result, and in the same transaction count the page as
    done and mark its page row done. Returns True if this call stored the
    result, False if an earlier delivery already had.

    Doing all three in one unit is what keeps ``pages_done`` equal to the
    number of stored results: a redelivery stores nothing and counts nothing,
    and a crash between the insert and the increment cannot happen.
    """
    with db.tx() as cur:
        cur.execute(
            "INSERT OR IGNORE INTO results (receipt, job_id, page_no, area_sqft, source) "
            "VALUES (?, ?, ?, ?, ?)",
            (receipt, job_id, page_no, area_sqft, source),
        )
        if cur.rowcount != 1:
            return False
        cur.execute(
            "UPDATE jobs SET pages_done = pages_done + 1, updated_at = ? WHERE job_id = ?",
            (stamp, job_id),
        )
        cur.execute(
            "UPDATE pages SET status = 'done' WHERE job_id = ? AND page_no = ?",
            (job_id, page_no),
        )
        return True

