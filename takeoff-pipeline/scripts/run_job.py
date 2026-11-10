"""Drive one job from the command line.

    python -m scripts.run_job --pages 120 --scale 48 --sheet ARCH_D
"""

import argparse
import sys
import time

from takeoff.core import ids
from takeoff.reporting.summary import render_summary
from takeoff.scheduler.orchestrator import run_job
from takeoff.storage.db import Database


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, default=40)
    parser.add_argument("--scale", type=int, default=48)
    parser.add_argument("--sheet", default="ARCH_D")
    parser.add_argument("--job-id", default=None)
    parser.add_argument("--db", default=":memory:")
    args = parser.parse_args(argv)

    db = Database(args.db)
    job_id = args.job_id or ids.new_job_id()
    started = time.monotonic()
    row = run_job(db, job_id, args.pages, scale=args.scale, sheet_size=args.sheet)
    elapsed = time.monotonic() - started
    print(render_summary(db, row))
    print("elapsed: {:.2f}s".format(elapsed))
    return 0 if row["status"] == "complete" else 1


if __name__ == "__main__":
    sys.exit(main())
