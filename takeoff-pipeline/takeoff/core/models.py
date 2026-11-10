from dataclasses import dataclass, field
from typing import Any

from . import ids


@dataclass(frozen=True)
class Job(object):
    job_id: str
    total_pages: int
    scale: int = 48
    sheet_size: str = "ARCH_D"
    fingerprint: str = ""


@dataclass(frozen=True)
class PageImage(object):
    """A rendered page as handed to the vision service."""

    page_no: int
    sheet_size: str
    scale: int
    data: bytes
    label: str = ""


@dataclass(frozen=True)
class Measurement(object):
    area_sqft: float
    source: str = "vision"


@dataclass
class PageContext(object):
    """Everything one page invocation needs."""

    job: Job
    page_no: int
    attempt: int
    invocation_id: str
    gate: Any = field(default=None, repr=False)

    @property
    def receipt(self):
        return ids.receipt(self.job.job_id, self.page_no, self.invocation_id)
