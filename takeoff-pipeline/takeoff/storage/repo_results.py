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
