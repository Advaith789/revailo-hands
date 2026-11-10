from dataclasses import dataclass

from ..config import settings


@dataclass(frozen=True)
class RetryPolicy(object):
    max_attempts: int
    base_s: float
    cap_s: float
    jitter: bool = True


def policy_from_settings():
    sec = settings.section("retry")
    return RetryPolicy(
        max_attempts=int(sec.get("max_attempts", 4)),
        base_s=float(sec.get("backoff_base_s", 0.01)),
        cap_s=float(sec.get("backoff_cap_s", 0.5)),
        jitter=bool(sec.get("jitter", True)),
    )


def attempts(policy):
    """Attempt numbers, 1-based, for the given policy."""
    return range(1, policy.max_attempts + 1)
