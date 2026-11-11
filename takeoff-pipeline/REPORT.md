# Part 1 Report

## How to run the tests

```bash
pip install pytest
cd takeoff-pipeline
python -m pytest                 # fixed code: 44 passed
python -m pytest -k d1           # one defect only (d1 to d8)
scripts/before_after.sh          # runs the tests and the numbers on the original code and on the fixed code
python -m scripts.evidence       # prints the before/after numbers
```

The git tag `original` holds the code exactly as received. Result: **original 16 failed, 28 passed. Fixed 44 passed.** The full output is in [evidence/before_after.txt](evidence/before_after.txt).

## Defects found (ranked by customer impact)

1. **D4. Rate limiter switched off.** Totals too low when many jobs run at once.
2. **D1. Retried pages saved twice.** Totals too high, by a different amount each run.
3. **D2. Failed pages ignored when finishing.** Large jobs hang, and some say "complete" too early.
4. **D3. Cache ignores drawing scale.** A corrected re-run returns the old number.
5. **D5. Duplicate sheet labels.** Some pages in sets over 199 pages get another page's number.
6. **D6. Wrong timezone.** Every timestamp is 6 hours off.
7. **D7. Database closed mid-write.** Crashed the original test run. This affects only the local copy.
8. **D8. Lambda handler has no limiter.** Crashes on every cache miss.

---

### D4. Rate limiter switched off
- **Test:** `test_d4_concurrent_jobs_stay_under_the_account_wide_vision_limit` and two related tests.
- **Fix:** Moved `shared_gate` from `[vision]` to `[flags]` in `settings.toml`, made it default to on, and added a warning for flags placed in the wrong section.
- **Before → after:** With 10 jobs at once, 246 of 1,235 pages were missing from totals and about 2,350 calls were rejected. After the fix, 0 and 0.
- **Why:** The release put the flag in the wrong section, so the code never read it. Each job then got its own limit of 10, while the service allows only 10 for the whole account. One job alone is fine, but the more jobs run together, the more calls get rejected. Pages that are still rejected after 4 retries are left out of the total, while the job still says "complete". Busy mornings and large accounts run the most jobs at once. No test ran two jobs together or read the real settings file.

### D1. Retried pages saved twice
- **Test:** `test_d1_a_failed_progress_event_does_not_count_the_page_twice` (12 results saved for a 10-page job).
- **Fix:** Results are now keyed by job and page only. Saving, counting and marking the page done happen in one transaction.
- **Before → after:** Average error of +2.2% to +5.4%, worst +9%. After the fix, exact.
- **Why:** The result key included an ID that changes on every attempt. When the progress update failed (about 4% of the time), the page was retried and saved again. The error is random, so the same plans give a different total each run, which is why it "feels" off. The tests turned progress updates off. One existing test even checked for this bug as correct behaviour, so I corrected that test.

### D2. Failed pages ignored when finishing
- **Test:** `test_d2_job_with_an_unrenderable_page_settles_promptly` and `test_d2_a_job_is_never_reported_complete_with_pages_outstanding`.
- **Fix:** A job is finished when pages done plus pages failed equals the total.
- **Before → after:** 15 of 15 large jobs got stuck until the timeout. After the fix, all finished in under 0.25 seconds. Jobs marked "complete" with pages still running went from 4 of 5 to 0 of 20.
- **Why:** One page in every 97 cannot be rendered, so every set of 97 pages or more could never reach "all pages done". It always waited the full 20-second timeout, which is the slowness. Combined with D1, the count could also hit the total early and show a partial number as complete. The only full-job test used 8 pages.

### D3. Cache ignores drawing scale
- **Test:** `test_d3_resubmitting_a_set_at_a_new_scale_gets_new_measurements`.
- **Fix:** The cache is now keyed on the page content itself, with a `v2` prefix so old cache entries are never used.
- **Before → after:** A re-run at scale 96 reported 9,397.14 instead of 8,801.79 (6.76% off). After the fix, exact.
- **Why:** The cache key used sheet size and page count but not scale. Anyone who corrected a wrong scale and re-ran within an hour got the old number back. The tests only checked that the same set gets the same key.

### D5. Duplicate sheet labels
- **Test:** `test_d5_every_page_of_a_full_size_set_is_a_distinct_drawing`.
- **Fix:** The label number is now the page's position in its series, as the code comment describes.
- **Before → after:** 4 duplicate pages per 500-page set (for example, page 199 matched page 100). After the fix, 0.
- **Why:** The label number wrapped at 99 while each series holds 100 sheets. This only happens past page 199, and no test went past 100 pages. Note that 304 of 500 labels change, so very large sets will show new numbers when re-run.

### D6. Wrong timezone
- **Test:** `test_d6_api_timestamps_are_actually_utc`.
- **Fix:** Times are saved in UTC, and older local times are converted when read.
- **Before → after:** 6 hours off. After the fix, correct.
- **Why:** Chicago time was saved and then labelled as UTC. No totals change. The test only checked that the time ended in "Z".

### D7. Database closed mid-write (local only)
- **Test:** `test_d7_closing_the_database_waits_for_an_in_flight_write`.
- **Fix:** `close()` now waits for any write in progress.
- **Before → after:** The original closed the database in the middle of a write (and crashed the test run). After the fix, close waits until the write finishes.
- **Why:** The original test run crashed while I was reproducing D2: a test closed the database while a page was still writing. This does not affect production.

### D8. Lambda handler has no limiter
- **Test:** `test_d8_lambda_handler_works_with_a_json_only_event`.
- **Fix:** The handler falls back to the shared limiter.
- **Before → after:** `TypeError` on a plain JSON event. After the fix, the page is measured and saved.
- **Why:** It expected a limiter inside the event, but a real Lambda event is plain JSON, so every cache miss crashed with a `TypeError`.

---

## Ruled out

- **Page counter update:** It reads and then writes, but under one lock. The existing test gives exactly 800 of 800 with 32 threads.
- **Square metre conversion (0.09290304):** It is exactly 0.3048².
- **Retry backoff:** It stays within the cap. The test gives 0.1, 0.2, 0.4, 0.5, 0.5, 0.5.
- **Every 97th page failing:** This is intentional and documented in the README.
- **Cache expiry:** It uses a monotonic clock, so timezone and daylight saving changes do not affect it.
- **Legacy runner counter:** It has no lock, but nothing calls it and the runner is turned off.
- **Progress bar capped at 100%:** It hid D1, but it is not wrong in itself.

## Shared limit in the cloud

**Enforcing the limit of 10 across all jobs and environments.** I would use a DynamoDB table with 10 slots that every environment shares. A worker claims a free slot with a conditional write before calling the service and releases it afterwards. Each claim expires, so a crashed Lambda cannot hold a slot forever. If no slot is free, Step Functions retries with backoff.

**Fixes that need a different mechanism once each page runs in its own Lambda:**
- **D4 and D8:** The in-memory limiter becomes the slot table.
- **D1:** The single database transaction becomes a DynamoDB transaction: save only if the result does not exist, and add 1 to the count.
- **D2:** The Map state decides when the job is finished, instead of polling the counters.
- **D3:** The in-memory cache becomes a DynamoDB table keyed on the page content.

## Note for customer success

> Thanks for telling us the totals felt off. You were right, and we have fixed it.
>
> - Some pages were counted twice, so totals were often a few percent too high.
> - On busy mornings, some pages were left out, so totals were too low.
> - Re-running a set with a corrected scale could return the old numbers.
> - A few pages in very large sets showed another page's measurement.
>
> All of this is fixed, and totals now match a page-by-page check exactly. If you re-run a recent set, the new number may be different. The new one is correct. We can send corrected totals for any recent project, so just tell us which ones matter most.

## How confident I am

**What I am sure of.** I am confident these eight defects explain the complaint: too high (D1), too low on busy mornings (D4), slow (D2), and corrected re-runs not changing (D3). I cannot be sure I found everything, because production runs code I cannot see.

**What I suspect but could not prove.** In production, the cache key never looked at the actual PDF. Two different customers' sets with the same size, scale and page count would share cached numbers. The D3 fix closes this, but it cannot be shown locally.

**What I would look at next.** Rejected calls and failed pages by hour in production, and how many old jobs have duplicate results.

**What would change my mind.** Production reads settings from AWS Parameter Store, not this file. If Parameter Store has `shared_gate` in the right place, D4 is not the production cause of the slow mornings.

## Extras

- **Ground-truth test:** A test runs four large jobs at once with real random failures and checks every total against a direct page-by-page measurement, to the cent.
- **Before/after script:** One command runs everything on both the original code and the fixed code.
- **Defects that hide each other:** D3 was hiding D4. The broken cache reduced the number of calls to the service, so fixing D3 alone would make D4 worse. They should be released together.
