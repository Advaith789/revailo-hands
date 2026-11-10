"""Feature flags.

Flags live in the ``[flags]`` section of settings and are evaluated once at
import, like every other setting. A flag that is not set is off.
"""

import logging

from .loader import settings


def _truthy(raw):
    if isinstance(raw, str):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return bool(raw)


def _flag(name, default=False):
    return _truthy(settings.section("flags").get(name, default))


MEASUREMENT_CACHE = _flag("measurement_cache", True)
PROGRESS_EVENTS = _flag("progress_events", True)
STRICT_SCHEMA = _flag("strict_schema", True)
LEGACY_RUNNER = _flag("legacy_runner", False)
SHARED_GATE = _flag("shared_gate", True)


def misplaced():
    """Flag names set outside ``[flags]``. Such a key is silently ignored,
    which is how ``shared_gate`` ended up under ``[vision]`` and turned the
    shared vision gate off without anything going red."""
    names = {"measurement_cache", "progress_events", "strict_schema", "legacy_runner", "shared_gate"}
    return sorted(
        "[{}] {}".format(section, key)
        for section, values in settings.as_dict().items()
        if section != "flags" and isinstance(values, dict)
        for key in values
        if key in names
    )


if misplaced():
    logging.getLogger("takeoff.flags").warning(
        "feature flags set outside [flags] are ignored: %s", ", ".join(misplaced())
    )


def snapshot():
    return {
        "measurement_cache": MEASUREMENT_CACHE,
        "progress_events": PROGRESS_EVENTS,
        "strict_schema": STRICT_SCHEMA,
        "legacy_runner": LEGACY_RUNNER,
        "shared_gate": SHARED_GATE,
    }
