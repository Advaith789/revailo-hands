"""Thin client over the vision service: gates concurrency, maps the
service's failure modes onto the pipeline's exception hierarchy, records
metrics."""

from ..core.errors import VisionUnavailable
from ..core.models import Measurement
from . import metrics, vision


def analyze(page, gate):
    """Measure one rendered page. ``gate`` bounds in-flight calls."""
    with metrics.timer("vision.analyze"):
        try:
            with gate:
                raw = vision.analyze_page(page.data)
        except vision.Throttled as exc:
            metrics.incr("vision.throttled")
            raise VisionUnavailable("throttled: {}".format(exc)) from exc
        except TimeoutError as exc:
            metrics.incr("vision.timeout")
            raise VisionUnavailable("timeout: {}".format(exc)) from exc
    metrics.incr("vision.ok")
    return Measurement(area_sqft=float(raw["area_sqft"]), source="vision")
