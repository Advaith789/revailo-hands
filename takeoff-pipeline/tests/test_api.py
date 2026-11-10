from unittest.mock import patch

import pytest

from takeoff.api import app
from takeoff.core.errors import NotFound, ValidationError
from takeoff.core.models import Measurement


def test_submit_then_poll_to_completion(db):
    with patch("takeoff.workers.page_worker.vision_client.analyze", return_value=Measurement(12.5)), patch(
        "takeoff.workers.page_worker.progress.publish"
    ):
        body = app.submit_job(db, {"job_id": "api-1", "total_pages": 6})
        assert body["status"] == "running"
        assert body["created_at"].endswith("Z")
        final = app.wait(db, "api-1")
    assert final["status"] == "complete"
    assert final["progress_pct"] == 100.0
    totals = app.get_totals(db, "api-1")
    assert totals["measured_pages"] == 6
    assert totals["total"] == pytest.approx(75.0)


def test_submit_is_idempotent_per_job_id(db):
    with patch("takeoff.workers.page_worker.vision_client.analyze", return_value=Measurement(1.0)), patch(
        "takeoff.workers.page_worker.progress.publish"
    ):
        first = app.submit_job(db, {"job_id": "api-2", "total_pages": 3})
        second = app.submit_job(db, {"job_id": "api-2", "total_pages": 3})
        app.wait(db, "api-2")
    assert first["job_id"] == second["job_id"]


def test_unknown_job_is_not_found(db):
    with pytest.raises(NotFound):
        app.get_job(db, "nope")


def test_bad_scale_is_rejected(db):
    with pytest.raises(ValidationError):
        app.submit_job(db, {"job_id": "api-3", "total_pages": 3, "scale": 50})
