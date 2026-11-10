"""Print the numbers behind each claim in REPORT.md.

    python -m scripts.evidence            # ~10 s on fixed code, ~2 min on original
    python -m scripts.evidence --seeds 10
    TAKEOFF_FLAGS__SHARED_GATE=false python -m scripts.evidence --only d4 --jobs 20

Uses only entry points that exist in both the original and the fixed tree, so
``scripts/before_after.sh`` runs this same file against both. The settle
timeout is cut to 5 s (via the documented env override) so jobs that never
settle cost 5 s each instead of 20 s; nothing else is changed.

Ground truth for a set is one direct, sequential, uncached vision call per
renderable page; the vision service is deterministic on page bytes.
"""

import os

os.environ.setdefault("TAKEOFF_SCHEDULER__COMPLETION_TIMEOUT_S", "5")

import argparse  # noqa: E402
import random  # noqa: E402
import statistics  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from unittest.mock import patch  # noqa: E402

from takeoff.api import app  # noqa: E402
from takeoff.api.schemas import build_job  # noqa: E402
from takeoff.cache import memo  # noqa: E402
from takeoff.config import flags  # noqa: E402
from takeoff.reporting import totals  # noqa: E402
from takeoff.scheduler.orchestrator import run_job  # noqa: E402
from takeoff.services import vision  # noqa: E402
from takeoff.storage.db import Database  # noqa: E402
from takeoff.workers import render  # noqa: E402

PUBLISH = "takeoff.workers.page_worker.progress.publish"


def true_total(job):
    total = 0.0
    for p in range(1, job.total_pages + 1):
        if p % render.CORRUPT_EVERY == 0:
            continue
        data = render.render_page(job, p).data
        while True:
            try:
                total += vision.SERVICE.analyze(data)["area_sqft"]
                break
            except TimeoutError:
                pass
    vision.SERVICE.reset_counters()
    return total


def pct(a, b):
    return round(100.0 * (a - b) / b, 4) + 0.0 if b else 0.0


def size_sweep(seeds):
    print("\n[D1, D2] one job at a time, real progress failures and vision timeouts")
    print("{:>6} {:>9} {:>10} {:>12} {:>14} {:>12} {:>10}".format(
        "pages", "complete", "stuck", "dup rows", "error vs truth", "worst error", "mean time"))
    for pages in (40, 96, 120, 250, 500):
        truth = true_total(build_job("truth", pages))
        statuses, dups, errs, secs = [], [], [], []
        for seed in range(seeds):
            random.seed(seed)
            memo.clear()
            db = Database()
            job_id = "sz-{}-{}".format(pages, seed)
            started = time.monotonic()
            row = run_job(db, job_id, pages)
            secs.append(time.monotonic() - started)
            statuses.append(row["status"])
            distinct = db.query_one(
                "SELECT COUNT(DISTINCT page_no) FROM results WHERE job_id = ?", (job_id,))[0]
            dups.append(totals.measured_pages(db, job_id) - distinct)
            errs.append(pct(totals.job_total(db, job_id), truth))
        print("{:>6} {:>9} {:>10} {:>12} {:>+13.2f}% {:>+11.2f}% {:>9.2f}s".format(
            pages, statuses.count("complete"), statuses.count("stuck"),
            "{:.1f}/run".format(statistics.mean(dups)), statistics.mean(errs),
            max(errs, key=abs), statistics.mean(secs)))


def premature_completion(seeds):
    print("\n[D2] jobs reported 'complete' while pages were still unmeasured")
    early = runs = 0
    for seed in range(seeds * 4):
        random.seed(1000 + seed)
        memo.clear()
        db = Database()
        job_id = "early-{}".format(seed)
        row = run_job(db, job_id, 60)
        if row["status"] != "complete":
            continue
        runs += 1
        pending = db.query_one(
            "SELECT COUNT(*) FROM pages WHERE job_id = ? AND status = 'pending'", (job_id,))[0]
        measured = totals.measured_pages(db, job_id)
        distinct = db.query_one(
            "SELECT COUNT(DISTINCT page_no) FROM results WHERE job_id = ?", (job_id,))[0]
        if pending or distinct < 60:
            early += 1
            if early == 1:
                print("  example: status=complete pages_done={} distinct pages stored={} "
                      "pending={}".format(row["pages_done"], distinct, pending))
        del measured
    print("  {} of {} 'complete' 60-page jobs were complete early".format(early, runs))


def memo_scale():
    print("\n[D3] same set re-run at a corrected scale within the memo TTL")
    memo.clear()
    db = Database()
    with patch(PUBLISH):
        run_job(db, "m-48", 40, scale=48)
        run_job(db, "m-96", 40, scale=96)
    truth = true_total(build_job("t", 40, scale=96))
    got = totals.job_total(db, "m-96")
    print("  scale 96 total: reported {:,.2f}  truth {:,.2f}  error {:+.2f}%".format(
        got, truth, pct(got, truth)))


def concurrency(n_jobs=10):
    print("\n[D4] {} different ~120-page sets submitted together (a busy morning)".format(n_jobs))
    print("  flags.SHARED_GATE = {}".format(flags.SHARED_GATE))
    memo.clear()
    vision.SERVICE.reset_counters()
    db = Database()
    rows = {}
    scales = (12, 24, 48, 96, 192)
    sheets = ("ARCH_A", "ARCH_B", "ARCH_C", "ARCH_D", "ARCH_E")

    # Distinct page counts as well, so the sets are distinct under the
    # original fingerprint too (it ignored scale; see D3).
    def one(i):
        rows[i] = run_job(db, "c-%d" % i, 120 + i, scale=scales[i % 5], sheet_size=sheets[i // 5 % 5])

    with patch(PUBLISH):
        started = time.monotonic()
        threads = [threading.Thread(target=one, args=(i,)) for i in range(n_jobs)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.monotonic() - started
    retried = db.query_one("SELECT COALESCE(SUM(attempts - 1), 0) FROM pages")[0]
    lost = sum(r["pages_failed"] for r in rows.values()) - n_jobs  # one corrupt page per set
    renderable = sum(119 + i for i in range(n_jobs))
    print("  vision 429s: {}  extra attempts: {}  pages missing from totals (excl. corrupt): "
          "{} of {}  wall time: {:.2f}s".format(
              vision.SERVICE.throttled_count, retried, lost, renderable, elapsed))


def labels():
    print("\n[D5] drawings that render identically within one 500-page set")
    job = build_job("l", 500)
    seen = {}
    clashes = []
    for p in range(1, 501):
        if p % render.CORRUPT_EVERY == 0:
            continue
        data = render.render_page(job, p).data
        if data in seen:
            clashes.append((seen[data], p, render.sheet_label(p)))
        seen.setdefault(data, p)
    print("  {} pages share bytes with an earlier page: {}".format(
        len(clashes), ", ".join("p{}=p{} ({})".format(b, a, lab) for a, b, lab in clashes) or "-"))


def timestamps():
    print("\n[D6] API created_at vs real UTC")
    db = Database()
    with patch(PUBLISH):
        body = app.submit_job(db, {"job_id": "ts", "total_pages": 1})
        app.wait(db, "ts")
    api = datetime.strptime(body["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    skew = (api - datetime.now(timezone.utc)).total_seconds() / 3600.0
    print("  created_at={}  skew {:+.1f} h".format(body["created_at"], skew))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--jobs", type=int, default=10, help="concurrent sets for D4")
    parser.add_argument("--only", nargs="*", default=None,
                        help="sections to run: d1 d2 d3 d4 d5 d6 (default: all)")
    args = parser.parse_args(argv)
    sections = [
        ("d5", labels),
        ("d6", timestamps),
        ("d3", memo_scale),
        ("d4", lambda: concurrency(args.jobs)),
        ("d1", lambda: size_sweep(args.seeds)),
        ("d2", lambda: premature_completion(args.seeds)),
    ]
    for name, fn in sections:
        if args.only is None or name in args.only:
            fn()


if __name__ == "__main__":
    main()
