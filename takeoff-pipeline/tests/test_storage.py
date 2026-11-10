import threading

from takeoff.api.schemas import build_job
from takeoff.storage import repo_jobs, repo_pages, repo_results


def test_increment_done_is_exact_under_contention(db):
    repo_jobs.create(db, build_job("st-1", 1))
    threads = [
        threading.Thread(target=lambda: [repo_jobs.increment_done(db, "st-1") for _ in range(25)])
        for _ in range(32)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert repo_jobs.get(db, "st-1")["pages_done"] == 800


def test_duplicate_receipt_is_not_stored_twice(db):
    repo_jobs.create(db, build_job("st-2", 1))
    assert repo_results.record(db, "r1", "st-2", 1, 10.0) is True
    assert repo_results.record(db, "r1", "st-2", 1, 10.0) is False
    assert repo_results.count(db, "st-2") == 1


def test_page_rows_are_created_with_the_job(db):
    repo_jobs.create(db, build_job("st-3", 5))
    assert repo_pages.count_by_status(db, "st-3") == {"pending": 5}
    repo_pages.set_status(db, "st-3", 2, "done")
    assert repo_pages.count_by_status(db, "st-3") == {"pending": 4, "done": 1}
