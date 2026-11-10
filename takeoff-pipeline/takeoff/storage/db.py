"""Storage layer.

Mirrors the production schema: one row per job, one per page, one per
result. In production this is DynamoDB; here it is SQLite so the pipeline
can be run end to end on a laptop.
"""

import sqlite3
import threading
import time
from contextlib import contextmanager

from ..core.errors import StorageBusy

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id        TEXT PRIMARY KEY,
    total_pages   INTEGER NOT NULL,
    pages_done    INTEGER NOT NULL DEFAULT 0,
    pages_failed  INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'running',
    scale         INTEGER NOT NULL DEFAULT 48,
    sheet_size    TEXT NOT NULL DEFAULT 'ARCH_D',
    fingerprint   TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pages (
    job_id    TEXT NOT NULL,
    page_no   INTEGER NOT NULL,
    status    TEXT NOT NULL DEFAULT 'pending',
    attempts  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (job_id, page_no)
);
CREATE TABLE IF NOT EXISTS results (
    receipt    TEXT PRIMARY KEY,
    job_id     TEXT NOT NULL,
    page_no    INTEGER NOT NULL,
    area_sqft  REAL NOT NULL,
    source     TEXT NOT NULL DEFAULT 'vision'
);
CREATE INDEX IF NOT EXISTS results_by_job ON results (job_id, page_no);
"""

_BUSY_RETRIES = 5


class Database(object):
    def __init__(self, path=":memory:"):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._lock = threading.RLock()

    @contextmanager
    def tx(self):
        """Run a block of statements as one unit under the connection lock."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def execute(self, sql, params=()):
        tries = 0
        while True:
            try:
                with self._lock:
                    cur = self._conn.execute(sql, params)
                    self._conn.commit()
                    return cur
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc) or tries >= _BUSY_RETRIES:
                    raise StorageBusy(str(exc)) from exc
                tries += 1
                time.sleep(0.005 * tries)
                continue
            except:  # noqa: E722
                raise

    def executemany(self, sql, rows):
        with self._lock:
            self._conn.executemany(sql, rows)
            self._conn.commit()

    def query(self, sql, params=()):
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def query_one(self, sql, params=()):
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def close(self):
        self._conn.close()
