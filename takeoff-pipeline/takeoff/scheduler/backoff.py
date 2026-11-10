import random


def delay(policy, attempt):
    """Seconds to wait after a failed ``attempt`` (1-based)."""
    base = policy.base_s * (2 ** (attempt - 1))
    capped = min(base, policy.cap_s)
    if policy.jitter:
        return capped * random.uniform(0.5, 1.5)
    return capped
