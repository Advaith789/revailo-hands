"""takeoff: local reproduction of the plan-takeoff service.

Importing the package wires up logging and loads settings once. Everything
else is imported on demand by the entry points in takeoff.api.app and
takeoff.scheduler.orchestrator.
"""

from .util.logging import configure as _configure_logging

_configure_logging()

__version__ = "2.7.1"
