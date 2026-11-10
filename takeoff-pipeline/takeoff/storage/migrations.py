"""Schema migrations.

Applied by the deploy job in production (the DynamoDB tables are created by
Terraform; these cover the SQLite replica the reporting jobs read from). The
local harness applies ``db.SCHEMA`` directly and never calls ``apply``.
"""

MIGRATIONS = [
    (1, "ALTER TABLE jobs ADD COLUMN scale INTEGER NOT NULL DEFAULT 48"),
    (2, "ALTER TABLE jobs ADD COLUMN sheet_size TEXT NOT NULL DEFAULT 'ARCH_D'"),
    (3, "ALTER TABLE results ADD COLUMN source TEXT NOT NULL DEFAULT 'vision'"),
    (4, "ALTER TABLE jobs ADD COLUMN fingerprint TEXT NOT NULL DEFAULT ''"),
    (5, "CREATE INDEX IF NOT EXISTS results_by_job ON results (job_id, page_no)"),
]


def current_version(db):
    db.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = db.query_one("SELECT MAX(version) FROM schema_version")
    return row[0] or 0


def apply(db):
    have = current_version(db)
    for version, sql in MIGRATIONS:
        if version <= have:
            continue
        try:
            db.execute(sql)
        except Exception as exc:  # column already present on fresh schemas
            if "duplicate column" not in str(exc):
                raise
        db.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
    return current_version(db)
