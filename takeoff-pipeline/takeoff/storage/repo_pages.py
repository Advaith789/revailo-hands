def bump_attempts(db, job_id, page_no):
    db.execute(
        "UPDATE pages SET attempts = attempts + 1 WHERE job_id = ? AND page_no = ?",
        (job_id, page_no),
    )


def set_status(db, job_id, page_no, status):
    db.execute(
        "UPDATE pages SET status = ? WHERE job_id = ? AND page_no = ?",
        (status, job_id, page_no),
    )


def get(db, job_id, page_no):
    row = db.query_one(
        "SELECT page_no, status, attempts FROM pages WHERE job_id = ? AND page_no = ?",
        (job_id, page_no),
    )
    if row is None:
        return None
    return {"page_no": row[0], "status": row[1], "attempts": row[2]}


def count_by_status(db, job_id):
    rows = db.query(
        "SELECT status, COUNT(*) FROM pages WHERE job_id = ? GROUP BY status", (job_id,)
    )
    return {status: n for status, n in rows}
