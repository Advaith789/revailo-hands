# Part 1: "the numbers feel off", investigation report

## Summary

The complaint describes three symptoms: totals feel off, the app is slow some mornings, and ops sees everything green. I found eight defects. Four of them change the numbers customers see, and the four interact. All eight are reproduced by tests that fail on the code as received, and all are fixed.

| # | Defect | Customer impact | Before → after (from [evidence/before_after.txt](evidence/before_after.txt)) |
|---|---|---|---|
| D4 | The shared vision gate is off: the "config only" release put `shared_gate` under `[vision]`, and the code only reads `[flags]` | **Totals too low on busy mornings.** Pages are rejected by the vision service (HTTP 429, "too many requests"), run out of retries and drop out of the total. The job still says "complete". | 10 concurrent sets: **246 of 1,235 pages missing** and 2,378 rejected calls → **0 missing, 0 rejected** |
| D1 | A retried page is stored twice, because the result key includes the per-attempt invocation id | **Totals too high on every job**, by a different amount each run | Mean error **+2.2% to +5.4%**, worst **+9.0%** → **±0.00%** |
| D2 | A job is "settled" only when `pages_done == total_pages`, so failed pages are ignored | **Slow and inconsistent.** Every set of 97+ pages waits out the full timeout and ends `stuck`. Some jobs are reported `complete` while pages are still being measured. | 120/250/500 pages: **15/15 stuck**, mean 5.01 s (20 s in production settings) → **15/15 complete in 0.07–0.23 s**. Early "complete": **4 of 5** → **0 of 20** |
| D3 | The measurement memo key ignores the drawing scale | **A re-run at a corrected scale returns the old scale's numbers** (for an hour, the memo TTL) | Reported 9,397.14 against a true 8,801.79 (**+6.76%**) → **exact** |
| D5 | The sheet label number uses modulus 99 over series of 100, so labels collide | In sets of 199+ pages, 4 pages get another page's measurement | 4 colliding pages per 500-page set → 0 |
| D6 | Timestamps are stored in Chicago wall-clock time but served with a `Z` (UTC) suffix | Every API timestamp is wrong by 5–6 h. Since DST ended on Nov 1 it is wrong by 6 h, and ordering by time is ambiguous for one hour a year. | Skew **−6.0 h** → **0.0 h** |
| D7 | `Database.close()` doesn't take the connection lock | Harness only: closing the database while a page worker is writing crashed the interpreter (segfault observed during this investigation) | Close completes mid-write → close waits for the write |
| D8 | `lambda_handler` takes its concurrency gate from the event, but a JSON event cannot carry one | The deployed-shape entry point crashes on every memo miss | `TypeError` → works |

**How they interact.** These interactions matter for both the diagnosis and the rollout:
- **D1 causes part of D2.** Duplicate rows push `pages_done` past `total_pages`, so jobs with no bad page also get stuck: 3 of 5 runs at 40 pages, 4 of 5 at 96 pages. A duplicate can also make `pages_done` hit `total_pages` exactly while a page is still outstanding, which is how a job gets reported complete early.
- **D3 partly hid D4.** Because the memo key ignored scale, sets that differed only in scale shared measurements. That cut vision traffic, so the original lost 0 pages when 5 of 10 sets differed only by scale. **Fixing D3 without D4 would make the throttling losses worse. They must ship together.**

---

## How to reproduce

Python 3.8+ and pytest are required. The repository root has a git tag `original` holding the code exactly as received, and everything else is in the working tree.

```bash
pip install pytest
cd takeoff-pipeline

python -m pytest                           # fixed tree: 44 passed
python -m pytest -k d1                     # one claim (d1..d8, e2e)
scripts/before_after.sh                    # current tests + evidence against BOTH trees
python -m scripts.evidence                 # the numbers in this report (fixed tree)
python -m scripts.evidence --only d4 --jobs 20
TAKEOFF_FLAGS__SHARED_GATE=false python -m scripts.evidence --only d4   # D4 isolated
```

`scripts/before_after.sh` exports the `original` tag to a temp directory and copies this tree's `tests/` and `scripts/evidence.py` on top. It then runs both trees. Result on the original: **16 failed, 28 passed**. Result on the fixed tree: **44 passed**. The 16 failures are the 14 new reproduction tests plus the two corrected tests in `test_worker.py`. The full log is in [evidence/before_after.txt](evidence/before_after.txt).

**Ground truth.** The vision service is deterministic on page bytes ("a given page has one correct result"). So the correct total for a set is one direct, sequential, uncached call per renderable page, summed. The `true_total` helper computes it without going through the scheduler, worker, memo or store. `test_e2e_concurrent_mixed_jobs_match_ground_truth` runs four large sets at once, one of them a re-run at a corrected scale, with real random progress failures and vision timeouts. It asserts every total equals the ground truth to the cent.

**Determinism.** Each reproduction test forces its failure on purpose (for example, the progress event fails once on page 3), so it fails every time on the original rather than flakily. The randomized behaviour is measured separately in `scripts/evidence.py` and reported as rates. The fixed suite passed 25 of 25 repeated runs (15 before D7 and D8 were added, 10 after).

Measured numbers vary from run to run, because thread interleaving isn't seeded. The ranges quoted below come from four full before/after runs. The saved log is one of those runs.

---

## Defects, ranked by customer impact

### D4: the shared vision gate is off (the "config only" release)

**Where.** In [settings.toml](settings.toml), `shared_gate = true` sat under `[vision]`. [flags.py](takeoff/config/flags.py) reads flags only from `[flags]`, and the default was `False`. So `flags.SHARED_GATE` was `False`, and [dispatcher.gate_for](takeoff/scheduler/dispatcher.py) gave every job its own gate of 10 against an account-wide limit of 10.

**Reproduce.** These tests fail on the original:
- `test_d4_flags_in_shipped_settings_are_in_the_flags_section` reports misplaced flag `[vision] shared_gate`.
- `test_d4_shared_vision_gate_is_on_with_shipped_settings`.
- `test_d4_concurrent_jobs_stay_under_the_account_wide_vision_limit` records 99 rejected calls with 4 jobs.

**Fix.**
- Moved the key to `[flags]`.
- Made the default fail safe (`True`). The limit is account-wide, so a missing or misplaced key must never fall back to per-job gates.
- [flags.py](takeoff/config/flags.py) now logs a warning naming any flag set outside `[flags]`.
- The feature itself is unchanged.

**Evidence** (`python -m scripts.evidence --only d4 --jobs N`, 10–20 different sets of about 120 pages submitted together):

| | 10 jobs: missing pages / rejected calls | 20 jobs: missing pages / rejected calls |
|---|---|---|
| original | 241–248 of 1,235 (20%) / 2,334–2,378 | 997 of 2,570 (39%) / 6,397 |
| fixed | 0 / 0 | 0 / 0 |
| fixed, gate forced off with `TAKEOFF_FLAGS__SHARED_GATE=false` | 263 / 2,333 | 1,015 / 6,311 |

The third row shows that the gate alone accounts for the loss.

**Why it manifests this way.**
- **Why that symptom.** Each job believes it may run 10 vision calls, so N concurrent jobs attempt 10×N against a limit of 10. Rejected calls are retried 4 times with 10–80 ms backoff, and pages that are still rejected are recorded as failed. Failed pages aren't in the total, but the job still settles as `complete`, so the number is quietly low.
- **Why at that scale, and why mornings.** With one job there is no effect, since 10 ≤ 10. The loss grows with the number of concurrent jobs (20% at 10, 39% at 20). Submissions bunch up when estimators start their day, and large accounts submit many sets at once.
- **Why ops saw green.** Jobs complete, and nothing alarms on `pages_failed` or `vision.throttled`.
- **Why the suite missed it.** No test runs two jobs at once. `test_limiter` proves the gate works, not that it's switched on. The config tests use temporary files, never the shipped `settings.toml`.

**On "slow".** Locally D4 does not slow jobs down: retries fail fast and the wall time is about the same (0.45 s off, 0.42 s on). In production a rejected call is retried with real Lambda and Step Functions backoff, so I'd expect D4 to add latency on busy mornings. That is an inference, not a measurement. The slowness I can measure is D2.

### D1: a retried page is stored and counted twice

**Where.** `ids.receipt(job_id, page_no, invocation_id)` ([ids.py](takeoff/core/ids.py)) is the primary key of `results`, and `invocation_id` is new for every attempt. The worker stores the result and increments `pages_done`, then publishes progress. Publishing fails about 4% of the time, the scheduler retries the page, and the retry stores a second row with a new receipt and increments again.

**Reproduce.** `test_d1_a_failed_progress_event_does_not_count_the_page_twice` fails on the original with `assert 12 == 10`: the progress event failed once each on pages 3 and 7, and 12 rows were stored for 10 pages. `test_redelivered_page_is_stored_and_counted_once` also fails.

**Fix.**
- The receipt is now derived from `(job_id, page_no)` only, and the invocation id stays in the logs.
- `repo_results.record_and_advance` stores the result, increments `pages_done` and marks the page done in **one transaction**, and only when the insert actually happened. So the counter always equals the number of stored results.
- `repo_jobs.record_page_failure` won't count a page as failed if its result is already stored. A page whose store succeeded but whose progress event failed 4 times is done, not failed.
- Progress events still publish on every attempt (the feature is unchanged), and retrying a page is now safe.

**Corrected test.** `test_receipts_are_unique_per_invocation` asserted `a != b` for two deliveries of the same page. Its docstring argued that otherwise "the second delivery is silently dropped", but dropping a redelivery is exactly what a receipt is for. The test asserted the defect, so I replaced it with `test_receipts_are_stable_across_deliveries`.

**Evidence** (`python -m scripts.evidence --only d1`, real random failures, 5 runs per size):
- Original: duplicate rows grow with set size, from 1.4 per run at 40 pages to 20.8 per run at 500 pages.
- Original: mean error is **+2.2% to +5.4%**, and the worst single run is **+9.0%** (+10.1% in an earlier run).
- Fixed: 0 duplicates and ±0.00% at every size.

**Why it manifests this way.**
- **Why "feels off" rather than "is wrong by X".** The error is random, so the same set gives a different, too-high total each time it runs. Nobody can point at a fixed wrong number, but anyone who re-runs or compares against a manual takeoff loses trust. That matches the complaint exactly.
- **Why everyone, but large accounts notice.** The percentage is roughly constant, but the absolute extra area grows with set size (about 21 extra pages on a 500-page set). Large accounts re-run more and cross-check more.
- **Why ops saw green.** `progress_pct` is capped at 100%, so a job with `pages_done = 125 / 120` displayed as a normal 100%.
- **Why the suite missed it.** Every job-level test patches `progress.publish` to a no-op, which removes the only failure that happens after the store, and one test asserted the bug as correct.

### D2: failed pages never count towards completion, and jobs complete early

**Where.** [completion.is_settled](takeoff/scheduler/completion.py) checked `pages_done == total_pages`.

**Reproduce.** These tests fail on the original:
- `test_d2_job_with_an_unrenderable_page_settles_promptly`: a 100-page job ends `stuck`.
- `test_d2_settled_accounts_for_failed_pages`.
- `test_d2_a_job_is_never_reported_complete_with_pages_outstanding`: on the original, `run_job` returned `complete` with page 10 still pending.

**Fix.** A job is settled when `pages_done + pages_failed == total_pages`. Equality is deliberate: now that D1 makes the counters exact, an overcount should surface as `stuck`, not pass silently. The legacy runner (the rollback path) uses the same check now, so rolling back wouldn't bring the bug back.

**Evidence.**
- Original: 120, 250 and 500 pages ended **15/15 stuck** after the full timeout (5.01 s with the evidence script's 5 s cap; production uses 20 s).
- Original: 40 and 96 pages, which contain no bad page, still ended stuck in 3/5 and 4/5 runs because of D1 overshoot.
- Original: **4 of 5** "complete" 60-page jobs had pages still pending. Example: `status=complete pages_done=60 distinct pages stored=59 pending=2`.
- Fixed: all complete in 0.03–0.23 s, and 0 of 20 complete early.

**Why it manifests this way.**
- **Why large sets.** Every set of 97+ pages contains an unrenderable page (one page in 97 is corrupt), so `pages_done` can reach at most `total_pages − 1`. The job therefore always waits out the whole timeout, which is the "slow" half of the complaint, and every large account hits it.
- **Why numbers change after "complete".** Combined with D1, a duplicate can make the counter hit `total_pages` exactly while pages are still outstanding. The job is then declared complete with a partial total, and the total keeps changing afterwards.
- **Why the suite missed it.** The only end-to-end test uses 8 pages with a mocked publisher, and no test runs a job containing page 97.
- **A related crash.** In this harness, a job completing early let the test end while a page was still writing. That is how D7 surfaced as a segfault.

### D3: the memo serves another scale's measurements

**Where.** `memo.key_for` returned `fingerprint:page_no`, and `set_fingerprint` hashed only `sheet_size|total_pages`. The README says a set is "fully described by its sheet size, its drawing scale and its page count".

**Reproduce.** `test_d3_memo_key_differs_when_the_drawing_scale_differs` and `test_d3_resubmitting_a_set_at_a_new_scale_gets_new_measurements` fail on the original.

**Fix.**
- The memo is now keyed on a hash of the rendered page bytes, versioned as `v2:<blake2b>`. That is exactly the vision service's own contract: "the same bytes always produce the same number". Two pages share a key if and only if they would get the same measurement, so a hit can't return another drawing's number. A genuine re-upload still hits, so `test_memo_key_is_stable_for_a_re_upload` still passes.
- The `v2:` prefix means entries written under the old scheme, which may still be in the production table until their TTL expires, are never read.
- `set_fingerprint` now also includes the scale, for anything else that relies on it.
- The memo feature itself is unchanged.

**Evidence.** A 40-page set run at scale 48 and then re-run at scale 96: the scale-96 total was reported as **9,397.14 against a true 8,801.79 (+6.76%)**. The reported figure is the scale-48 total. Fixed: **8,801.79, exact**.

**Why it manifests this way.**
- **Who it hits.** Estimators who fix a wrong scale and re-run within the hour. The memo docstring names re-uploads as the main use case, and heavy accounts do it most.
- **What they see.** The corrected run returns the same number as the wrong one, which is about the most trust-destroying thing a measuring tool can do.
- **Why the suite missed it.** The only memo key test checks that keys *match* for the same set, and nothing checks that they *differ* for different sets.

### D5: duplicate sheet labels in sets of 199+ pages

**Where.** [render.sheet_label](takeoff/workers/render.py) used `page_no % (SHEETS_PER_SERIES - 1)`: a modulus of 99 over series of 100 pages, which wraps once per series. Pages 100 and 199 are both `B-01`, and the same happens at 299, 399 and 499. The page bytes come from the label, so the second page got the first page's measurement.

**Reproduce.** `test_d5_every_page_of_a_full_size_set_is_a_distinct_drawing` fails on the original.

**Fix.** The number is now the sheet's 1-based position within its series, as the docstring specifies. Series A is pages 1–99 (there is no page 0), and B is pages 100–199 (`B-01` to `B-100`). Both documented examples still hold (page 1 is `A-01`, page 150 is `B-51`, pinned by `test_d5_sheet_labels_match_the_documented_examples`).

**Consequence to be aware of.** 304 of 500 labels change (pages 99, 198, 199 and everything from 200 up), and with them their measurements. The old labels were wrong by the docstring's own definition, not only the 4 that collided. Re-runs of sets over 200 pages will show different numbers, and the customer note says so. The memo's `v2` key keeps old entries from being reused.

**Evidence.** Before: 4 pages per 500-page set shared bytes with an earlier page (`p199=p100 (B-01)`, `p299=p200`, `p399=p300`, `p499=p400`). After: 0.

**Why the suite missed it.** No test renders more than 100 pages. **Caveat:** this renderer stands in for production PDF rasterisation. Whether production has an equivalent bug depends on how it derives sheet labels, which I can't see.

### D6: API timestamps are Chicago time labelled as UTC

**Where.** [clock.stamp](takeoff/core/clock.py) stored the region's wall-clock time, and [serializers.iso_utc](takeoff/api/serializers.py) appended `Z` without converting.

**Reproduce.** `test_d6_api_timestamps_are_actually_utc` fails on the original.

**Fix.** Stored stamps are UTC with an explicit offset. `iso_utc` converts any naive legacy row from the region timezone instead of relabelling it.

**Evidence.** Skew −6.0 h → 0.0 h.

**Impact.** It doesn't affect any numbers. It makes "when did this run" wrong in the app and in any audit, and naive local times sort ambiguously across the DST change on Nov 1. The suite only checked that the string ends in `Z`.

### D7: `Database.close()` races with in-flight writes (harness)

**Where and how found.** The original tree segfaulted while I was reproducing D2. The test ended, its fixture closed the SQLite connection, and a page worker was still inside `execute()`.

**Fix.** `close()` takes the connection lock. A late writer now gets a Python `ProgrammingError` instead of crashing the interpreter. `test_d7_closing_the_database_waits_for_an_in_flight_write` fails on the original, where close completed mid-write.

**Impact.** No production impact, since DynamoDB has no equivalent. I'm listing it because it made the original suite crash.

### D8: the Lambda-shaped handler can't receive a gate

**Where.** [handler.lambda_handler](takeoff/workers/handler.py) passed `event.get("gate")` as the concurrency gate. A JSON event can't carry one, so it was always `None`, and `with gate:` raised `TypeError` on every memo miss.

**Fix.** It falls back to the shared vision gate.

**Evidence.** `test_d8_lambda_handler_works_with_a_json_only_event` fails on the original with that `TypeError`.

**Impact.** Latent. Nothing in the harness calls it, but it is the documented deployed entry shape. In production the gate has to be the distributed token table (see below).

---

## Ruled out

| Looked at | Why it looks wrong | Why it's fine (evidence) |
|---|---|---|
| `repo_jobs.increment_done` reads then writes | Classic lost-update race | Both statements run inside `db.tx()` under one `RLock` on a single connection. `test_increment_done_is_exact_under_contention` gives exactly 800 of 800 with 32 threads, and it still passes. (The worker now uses an atomic `pages_done + 1` anyway.) |
| `legacy_runner._bump_done` | Unlocked read-modify-write | It is never called (dead code), and the runner is off (`legacy_runner = false`). I left it alone ("do not extend") and only pointed the runner's completion and failure paths at the fixed functions, so a rollback doesn't bring D1 or D2 back. |
| `units.SQM_PER_SQFT = 0.09290304` | Magic number | 0.3048² = 0.09290304 exactly, the international foot definition, and display units default to `sqft`. |
| `backoff.delay` and the retry policy | Jitter could exceed the cap | Jitter multiplies the capped value by 0.5–1.5, so it is bounded. `test_backoff_grows_and_is_capped` gives [0.1, 0.2, 0.4, 0.5, 0.5, 0.5]. |
| The 0.25 s status cache in `api.get_job` | Stale status | The TTL is short, and `app.wait` invalidates before reading. It is never stale after completion (`test_submit_then_poll_to_completion`). |
| Memo / `TTLCache` expiry | Clock problems | It uses `time.monotonic`, so wall-clock and DST changes can't affect it (`test_ttl_cache_expires`). |
| `vision_client` error mapping | Swallowed errors | `Throttled` and `TimeoutError` map to the retryable `VisionUnavailable`, and everything else propagates. That is correct for a dependency we don't own. |
| Pages divisible by 97 fail | Looks like a bug | Intended: the README says it models corrupt pages. The problem was only how completion treated them (D2). |
| `toml_lite` comment stripping and coercion | Hand-rolled parser | It handles `#` inside quoted strings and bool/int/float, and only parses the subset the file uses (`test_toml_lite_parses_sections_and_scalars`). |
| `Database.execute` "locked" retry loop | Possible infinite loop | Bounded at 5 retries. A single shared connection never reports locked, so it is a dormant safety net. |
| `per_job_concurrency = 10`, equal to the account limit | Looks like the bug | It is correct for a single job. The defect is using per-job gates for concurrent jobs at all (D4). |
| `progress_pct` capped at 100 | Hides overcounts | Correct as a display rule. It masked D1 on the dashboards, but it isn't itself wrong, so I kept it. |
| `schemas._int_field` uses `int(float(str(x)))` | Truncation | `"120.7"` becomes 120 pages. That is sloppy but has no customer impact: clients send integers, and strict schema rejects non-listed scales. Noted, not changed. |
| `migrations.apply` | Swallows exceptions | It only swallows "duplicate column" (fresh schemas already have it) and the harness never calls it. |

---

## Production: the shared vision limit, and which local fixes need a different mechanism

**Enforcing the account-wide limit of 10 across jobs and environments.** Each page is its own Lambda invocation, so an in-process semaphore bounds nothing. I'd use a **lease table in DynamoDB**:

1. Create one item per slot (`slot#0` to `slot#9`) in a single table that every environment (prod, staging, dev, possibly other accounts via a cross-account role) uses for the shared vision account.
2. A worker acquires a slot with a conditional write:
   - `PutItem` / `UpdateItem` on a slot,
   - with the condition `attribute_not_exists(owner) OR expires_at < :now`,
   - setting `owner = <request id>` and `expires_at = now + vision timeout + margin`.
3. It releases the slot with a conditional delete on `owner = <request id>`.
4. The expiry handles Lambdas that time out or crash mid-call. A plain counter would leak a permit on every crash.
5. If no slot is free, the Lambda throws a dedicated `NoVisionSlot` error. The Step Functions `Retry` on that error uses exponential backoff with jitter, so waiting costs no Lambda time.
6. Give non-production a fixed small share (for example 2 of the 10 slots) so staging load tests can't throttle customers.
7. Keep 429 handling as the backstop, since the limiter is an agreement among our callers, not a guarantee.

**Local fixes that need a different mechanism in Lambda:**

| Local fix | Lambda / DynamoDB equivalent |
|---|---|
| D4/D8 `limiter.shared` (process semaphore) | The lease table above. Per process means per invocation, which means no limit at all. |
| D1 deterministic receipt and `record_and_advance` (SQLite transaction, `INSERT OR IGNORE`) | Key the result item on `(job_id, page_no)`. Use one `TransactWriteItems`: a `Put` of the result with `attribute_not_exists(pk)` plus an `Update` of the job with `ADD pages_done 1`. Treat a failed condition as "already done". Map iterations and Lambda retries are at-least-once. |
| D1 `record_page_failure` (check for a result, then count the failure in one transaction) | A `TransactWriteItems` with a `ConditionCheck` that the result item doesn't exist, plus `ADD pages_failed 1`. |
| D2 completion polling of counters | Let the `Map` state be the completion signal. It finishes when every iteration has succeeded or been caught. A `Catch` per iteration records the failure, and a final state reads the totals. The counters then serve only the progress bar. |
| D3 content-addressed memo (dict) | A DynamoDB memo table keyed by `v2#sha256(rasterised page)`, with a TTL attribute. No conditional write is needed, since one key always maps to one value. |
| D6 UTC stamps | Unchanged. The bug is the explicit `ZoneInfo("America/Chicago")`, not the Lambda's TZ. |
| D7 `close()` lock | Not applicable. |

**Data cleanup.** Already-stored jobs keep their duplicate rows. Find them with a query of results by `job_id`, grouping by `page_no` with count > 1. Recompute those jobs' totals and give customer success the list of affected job IDs with corrected numbers.

---

## Note for customer success

> **Subject: Why your takeoff totals may have felt off, and what we fixed**
>
> Thank you for flagging that recent takeoff totals felt less reliable. You were right, and we found the causes.
>
> **What was happening**
>
> - **Some pages were counted twice.** When part of our system had a brief hiccup, it sometimes measured a page again and added it to the total a second time. This made totals a few percent too high (usually 2 to 5 percent, occasionally up to about 10), and by a different amount each time, which is why the same plan set could give different results.
> - **Some pages were left out on busy mornings.** When many plan sets were being processed at once, a safety setting that stops us overloading our measuring service had been accidentally switched off in a recent update. Pages that couldn't be measured were left out of the total without warning, which made totals too low.
> - **Correcting the drawing scale didn't always work.** If you re-ran a set within an hour after fixing its scale, you could get the old numbers back.
> - **A few pages in very large sets (around 200 pages or more) were mixed up** and reported another page's measurement.
> - **Large sets were slow to finish,** and sometimes showed as finished before every page was measured.
>
> **What we've done**
>
> All of these are fixed. Every total now matches a page-by-page check exactly in our testing, including large sets and busy periods.
>
> **What this means for you**
>
> - **New runs can be trusted.** If you re-run a recent set, the new total may differ from the one you saw before. The new number is the correct one.
> - **Sets over 200 pages** may show more changes than smaller ones, because some of their pages were being identified incorrectly.
> - **Past results.** We are going through recent jobs to find the ones affected and can send you corrected totals for specific plan sets. Please tell us which projects matter most to you.
>
> We're sorry for the uncertainty this caused, and thank you for raising it.

---

## Confidence, open suspicions, next steps

**Confidence.** High that these eight defects are real, are fixed, and explain the complaint:
- Too high comes from D1.
- Too low on busy mornings comes from D4.
- "Feels" off, meaning it varies run to run, comes from D1, D2 and D4.
- Re-runs not changing comes from D3.
- Slow comes from D2 (measured) and D4 (inferred).
- Ops green comes from complete statuses, the progress cap and no alarms on failed pages.

The end-to-end ground-truth test and the evidence sweep found no remaining error in the fixed tree. I'm moderately confident this is everything in the local reproduction. I can't be sure about production, which runs code I can't see.

**Suspected but not proven:**
1. **The production memo may mix up different customers' drawings.** The fingerprint has never included anything from the PDF itself, only sheet size and page count, and now scale. Locally that is a set's full identity. In production, two different customers' 120-page ARCH_D sets at the same scale would share memo keys for an hour. The content-hash key (D3 fix) closes this, but I can't demonstrate it locally because the harness defines a set by those three values. **This is the first thing I'd check in production.**
2. **Release attribution.** D4 fits "a release around a month ago that was all config". D1, D2 and D5 look long-standing: the D1 test has "passed for months". There's no git history to confirm either.
3. **D4 latency in production.** As described in D4, it is inferred, not measured.
4. **Unhandled non-pipeline exceptions in pool threads** (any exception that isn't a `TakeoffError`) are swallowed by `ThreadPoolExecutor`. The page then never reaches a terminal state and the job ends `stuck`. I never observed it, so I didn't change it.

**What I'd look at next:**
- Production vision 429 counts and failed-page counts by hour.
- Memo hit rates by account, and whether any memo key is shared across accounts.
- The SSM values under `/flags/` against `/vision/`.
- The duplicate-results query above across the last 60 days, to size the historical impact per account.

**One observation that would change my diagnosis.** Production reads settings from SSM Parameter Store, not this `settings.toml`. **If SSM has `flags/shared_gate = true` correctly placed,** then the misplaced key is a local artifact and D4 isn't what's happening in production. I'd then expect production 429 counts to be flat on slow mornings, and I'd look for the morning slowness elsewhere: cold starts, or completion polling against an eventually consistent read.

---

## Files changed

- **Fixes:**
  - [takeoff/core/ids.py](takeoff/core/ids.py), [takeoff/core/models.py](takeoff/core/models.py)
  - [takeoff/storage/repo_results.py](takeoff/storage/repo_results.py), [takeoff/storage/repo_jobs.py](takeoff/storage/repo_jobs.py), [takeoff/storage/db.py](takeoff/storage/db.py)
  - [takeoff/workers/page_worker.py](takeoff/workers/page_worker.py), [takeoff/workers/render.py](takeoff/workers/render.py), [takeoff/workers/handler.py](takeoff/workers/handler.py)
  - [takeoff/scheduler/completion.py](takeoff/scheduler/completion.py), [takeoff/scheduler/dispatcher.py](takeoff/scheduler/dispatcher.py), [takeoff/scheduler/legacy_runner.py](takeoff/scheduler/legacy_runner.py)
  - [takeoff/cache/memo.py](takeoff/cache/memo.py), [takeoff/api/schemas.py](takeoff/api/schemas.py), [takeoff/api/serializers.py](takeoff/api/serializers.py)
  - [takeoff/core/clock.py](takeoff/core/clock.py), [takeoff/config/flags.py](takeoff/config/flags.py), [takeoff/config/defaults.py](takeoff/config/defaults.py), [settings.toml](settings.toml)
- **Tests:** [tests/test_regressions.py](tests/test_regressions.py) (new), and [tests/test_worker.py](tests/test_worker.py) (one wrong test corrected, one added).
- **Tooling:** [scripts/evidence.py](scripts/evidence.py), [scripts/before_after.sh](scripts/before_after.sh), [evidence/before_after.txt](evidence/before_after.txt).
- **Untouched:** `takeoff/services/vision.py`. All README entry points keep their signatures.
