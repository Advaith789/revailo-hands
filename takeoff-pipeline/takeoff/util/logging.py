import logging
import os

_configured = False


def configure(level=None):
    global _configured
    if _configured:
        return
    level = level or os.environ.get("TAKEOFF_LOG_LEVEL", "WARNING")
    logging.basicConfig(
        level=getattr(logging, str(level).upper(), logging.WARNING),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _configured = True


def get_logger(name):
    return logging.getLogger("takeoff." + name)
