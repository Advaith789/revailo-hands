from datetime import datetime

from ..config import settings
from ..core import units


def iso_utc(stamp):
    """Render a stored timestamp for the API (RFC 3339, UTC)."""
    return datetime.fromisoformat(stamp).strftime("%Y-%m-%dT%H:%M:%SZ")


def progress_pct(row):
    if row["total_pages"] <= 0:
        return 0.0
    pct = 100.0 * row["pages_done"] / row["total_pages"]
    return min(100.0, round(pct, 1))


def job_row(row):
    return {
        "job_id": row["job_id"],
        "status": row["status"],
        "total_pages": row["total_pages"],
        "pages_done": row["pages_done"],
        "pages_failed": row["pages_failed"],
        "progress_pct": progress_pct(row),
        "scale": row["scale"],
        "sheet_size": row["sheet_size"],
        "created_at": iso_utc(row["created_at"]),
        "updated_at": iso_utc(row["updated_at"]),
    }


def totals_body(row, total_sqft, measured_pages):
    display = settings.section("display")
    unit = display.get("units", "sqft")
    decimals = int(display.get("decimals", 2))
    return {
        "job_id": row["job_id"],
        "status": row["status"],
        "total": round(units.convert(total_sqft, unit), decimals),
        "units": unit,
        "measured_pages": measured_pages,
        "failed_pages": row["pages_failed"],
        "total_pages": row["total_pages"],
    }
