"""Clocks.

Two wall clocks are in use: UTC for anything that crosses a boundary, and the
deployment region's wall clock for what the ops dashboards and the on-call
runbooks show. The monotonic clock is for intervals.
"""

import time
from datetime import datetime, timedelta, timezone

from ..config import settings

try:  # Python 3.9+
    from zoneinfo import ZoneInfo

    REGION_TZ = ZoneInfo(settings.app.timezone)
except Exception:  # pragma: no cover - older interpreters / missing tzdata
    REGION_TZ = timezone(timedelta(hours=-6), "CST")


def utc_now():
    return datetime.now(timezone.utc)


def wall_now():
    """Current wall-clock time in the deployment region, naive."""
    return datetime.now(REGION_TZ).replace(tzinfo=None)


def stamp():
    """Timestamp string for stored rows."""
    return wall_now().isoformat(timespec="seconds")


def monotonic():
    return time.monotonic()
