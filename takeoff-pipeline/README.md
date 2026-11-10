# takeoff-pipeline

Local reproduction of the plan-takeoff service. Same control flow as the
deployed system (API -> orchestrator -> per-page workers -> store), with AWS
swapped for in-process equivalents so a full job runs on a laptop.

| Production | Here |
| --- | --- |
| API Gateway + handler Lambda | `takeoff/api/` |
| Step Functions distributed map | `takeoff/scheduler/` (thread pool) |
| Per-page Lambda | `takeoff/workers/` |
| DynamoDB | `takeoff/storage/` (SQLite) |
| Measurement memo table | `takeoff/cache/memo.py` |
| SSM Parameter Store | `settings.toml` + `takeoff/config/` |
| Internal vision service | `takeoff/services/vision.py` |
| CloudWatch metrics | `takeoff/services/metrics.py` |

## Running

    pip install pytest
    python -m pytest

Python 3.8 or newer, standard library only.

## Layout

    takeoff/
      api/         request handlers, schema parsing, response serializers
      config/      settings loader, defaults, feature flags
      core/        models, ids, clocks, units, error hierarchy, retry policy
      scheduler/   fan-out, retry loop, completion check
      workers/     render -> measure -> store -> progress, per page
      storage/     SQLite schema and repositories
      cache/       measurement memo and a small TTL cache
      services/    vision client, concurrency gates, metrics
      reporting/   totals and the CLI summary
      util/        logging, timing, old shims
    scripts/       command-line driver
    tests/         the suite

## The vision service

`takeoff/services/vision.py` models a dependency we do not own: it is
metered, it enforces an account-wide limit on in-flight calls, and it
occasionally times out. Read that module for the exact contract. Do not
change it. It describes what we have to live with, not what we would like.

The local fixture measures a rendered page deterministically: the same bytes
always produce the same number. Timing and failures still vary.

## What a set is, locally

There is no PDF in the local harness. A set is fully described by its sheet
size, its drawing scale and its page count; `takeoff/workers/render.py`
derives each page's bytes from those, so two sets that differ in any of them
are different drawings as far as the vision service is concerned. Pages whose
number is a multiple of 97 are deliberately unrenderable; that models the
corrupt pages real plan sets contain.

## Driving a job

    from takeoff.storage.db import Database
    from takeoff.scheduler.orchestrator import run_job
    from takeoff.reporting import totals

    db = Database()
    row = run_job(db, "job-1", 120, scale=48, sheet_size="ARCH_D")
    print(row, totals.job_total(db, "job-1"))

or from a shell:

    python -m scripts.run_job --pages 120 --scale 48

`run_job` returns the job row once the job has settled, or marks it `stuck`
if it has not settled within `scheduler.completion_timeout_s`.

The API handlers in `takeoff/api/app.py` (`submit_job`, `get_job`,
`get_totals`, `wait`) are what the deployed service exposes; they take a
`Database` and a decoded request body.

## Settings

`settings.toml` at the repository root, with precedence documented in
`takeoff/config/loader.py`. Flags are in the `[flags]` section.

## Entry points the graders drive

Keep these working with their current signatures; our checks call them:
`run_job`, `Database`, the four `api.app` functions, `render.render_page`,
`schemas.build_job`, `memo.clear`, `totals.job_total`, and `vision.SERVICE`.
