"""Built-in defaults. Every key the code reads has a default here so a
missing settings file still yields a runnable service. Sections are open:
ops can add keys ahead of the code that reads them."""

DEFAULTS = {
    "app": {
        "name": "takeoff",
        "region": "us-east-2",
        "timezone": "America/Chicago",
        "log_level": "WARNING",
    },
    "vision": {
        "max_in_flight": 10,
        "timeout_s": 2.0,
    },
    "scheduler": {
        "pool_size": 24,
        "per_job_concurrency": 10,
        "completion_timeout_s": 20.0,
        "poll_interval_s": 0.02,
    },
    "retry": {
        "max_attempts": 4,
        "backoff_base_s": 0.01,
        "backoff_cap_s": 0.5,
        "jitter": True,
    },
    "cache": {
        "measurement_ttl_s": 3600,
        "status_ttl_s": 0.25,
    },
    "flags": {
        "measurement_cache": True,
        "progress_events": True,
        "strict_schema": True,
        "legacy_runner": False,
        "shared_gate": False,
    },
    "display": {
        "units": "sqft",
        "decimals": 2,
    },
}
