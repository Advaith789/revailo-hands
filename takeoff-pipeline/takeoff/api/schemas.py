"""Request parsing and the job model builder."""

import hashlib
from dataclasses import dataclass

from ..config import flags
from ..core import ids
from ..core.errors import ValidationError
from ..core.models import Job

SHEET_SIZES = ("ARCH_A", "ARCH_B", "ARCH_C", "ARCH_D", "ARCH_E")
# Drawing scale as real-world inches per drawn inch: 1/4" = 1' is 48.
SCALES = (12, 24, 48, 96, 192)
MAX_PAGES = 500


@dataclass(frozen=True)
class SubmitRequest(object):
    job_id: str
    total_pages: int
    scale: int
    sheet_size: str


def _int_field(payload, name, default=None):
    raw = payload.get(name, default)
    if raw is None:
        raise ValidationError("{} is required".format(name))
    try:
        return int(float(str(raw)))
    except (TypeError, ValueError):
        raise ValidationError("{} must be an integer, got {!r}".format(name, raw))


def parse_submit(payload):
    if not isinstance(payload, dict):
        raise ValidationError("body must be an object")
    job_id = str(payload.get("job_id") or ids.new_job_id())
    total_pages = _int_field(payload, "total_pages")
    scale = _int_field(payload, "scale", 48)
    sheet_size = str(payload.get("sheet_size", "ARCH_D")).upper()
    if flags.STRICT_SCHEMA:
        if not 1 <= total_pages <= MAX_PAGES:
            raise ValidationError("total_pages must be between 1 and {}".format(MAX_PAGES))
        if scale not in SCALES:
            raise ValidationError("scale must be one of {}".format(SCALES))
        if sheet_size not in SHEET_SIZES:
            raise ValidationError("sheet_size must be one of {}".format(SHEET_SIZES))
    return SubmitRequest(job_id=job_id, total_pages=total_pages, scale=scale, sheet_size=sheet_size)


def set_fingerprint(sheet_size, total_pages):
    """Stable identity for an uploaded set. Two uploads of the same set must
    fingerprint the same way or the measurement memo never hits."""
    raw = "{}|{}".format(sheet_size, int(total_pages))
    return hashlib.sha1(raw.encode("ascii")).hexdigest()[:16]


def build_job(job_id, total_pages, scale=48, sheet_size="ARCH_D"):
    return Job(
        job_id=str(job_id),
        total_pages=int(total_pages),
        scale=int(scale),
        sheet_size=str(sheet_size),
        fingerprint=set_fingerprint(sheet_size, total_pages),
    )
