"""v1 response shapes. The mobile client was moved to v2 in 2.5; these stay
until the last v1 build is out of the field (CS-881)."""

from . import serializers


def job_row_v1(row):
    body = serializers.job_row(row)
    return {
        "id": body["job_id"],
        "state": body["status"].upper(),
        "pages": body["total_pages"],
        "complete": body["pages_done"],
        "percent": int(body["progress_pct"]),
        "created": body["created_at"],
    }


def totals_v1(body):
    return {"id": body["job_id"], "sqft": body["total"], "pages": body["measured_pages"]}
