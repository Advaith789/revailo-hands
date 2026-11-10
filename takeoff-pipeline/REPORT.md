# Part 1: what's wrong with the takeoff numbers

## The short version

Customers said the totals "feel off" and the app is slow some mornings. They were right about both.

I found eight bugs. Four of them change the numbers people see, and they make each other worse. Every bug has a test that fails on the original code and passes now.

| # | Bug | What customers see | Before → after |
|---|---|---|---|
| D4 | The config release switched off the shared rate limiter | Totals too low when lots of jobs run at once | 10 jobs at once: 246 of 1,235 pages missing → 0 |
| D1 | A retried page gets saved twice | Totals too high, by a different amount each run | Average +2.2% to +5.4%, worst +9% → exact |
| D2 | Failed pages don't count toward "finished" | Big jobs hang until the timeout, and some say "complete" too early | 15 of 15 big jobs stuck → 0. Finished early: 4 of 5 → 0 of 20 |
| D3 | The cache ignores the drawing scale | Re-running with a corrected scale gives back the old number | 6.76% too high → exact |
| D5 | Sheet labels repeat past page 199 | 4 pages in a 500-page set get another page's number | 4 → 0 |
| D6 | Chicago time is labelled as UTC | Every timestamp in the app is 6 hours off | −6.0 h → 0 |
| D7 | The database can be closed while it's still writing | The local test run crashed (local only) | Crash → close waits |
| D8 | The Lambda-style handler never gets a rate limiter | That entry point crashes on every cache miss | `TypeError` → works |

Two things matter when shipping these:

- **D1 feeds D2.** Duplicate saves push the "pages done" count past the real page count, so even small jobs get stuck. Sometimes the count hits the target exactly while a page is still running, and the job says "complete" with a partial total.
- **D3 was hiding D4.** The broken cache key made different sets share results, which meant fewer calls to the measuring service and less throttling. If you fix D3 without D4, you'll lose more pages, not fewer. They need to go out together.

---

## How to run it

You need Python 3.8 or newer and pytest. The repo has a git tag called `original` that holds the code exactly as I got it.

```bash
pip install pytest
cd takeoff-pipeline

python -m pytest                       # fixed code: 44 passed
python -m pytest -k d1                 # just one bug (d1 to d8, or e2e)
scripts/before_after.sh                # runs the tests and the numbers on BOTH versions
python -m scripts.evidence             # prints the numbers in this report
TAKEOFF_FLAGS__SHARED_GATE=false python -m scripts.evidence --only d4   # D4 on its own
```

`before_after.sh` copies the original code to a temp folder, drops the new tests on top, and runs both versions. On the original, 16 tests fail and 28 pass. On the fixed code, all 44 pass. The full output is saved in [evidence/before_after.txt](evidence/before_after.txt).

**How I know what the right answer is.** The measuring service always returns the same number for the same page. So the true total is just one direct call per page, added up, with no cache, no scheduler and no database. The tests compare against that. The biggest test runs four large jobs at once, one of them a re-run at a corrected scale, with real random failures switched on. It checks every total to the cent.

**Keeping the tests reliable.** The bug tests force the failure on purpose, for example making the progress update fail once on page 3, so they fail every time on the original instead of now and then. The random behaviour is measured separately by the evidence script. I ran the fixed suite 25 times in a row, and it passed every time.

The numbers shift a little between runs, since thread timing isn't fixed. The ranges below come from four full runs.

---

## The bugs, worst first

### D4: the shared rate limiter was switched off

**What's wrong.** The measuring service allows only 10 calls at a time across the whole account. There's a setting, `shared_gate`, that makes all jobs share one limit of 10. The release put that setting under `[vision]` in [settings.toml](settings.toml), but the code only reads flags from `[flags]`. So the setting was ignored, the flag defaulted to off, and every job got its own limit of 10.

**Tests.** These fail on the original:
- `test_d4_flags_in_shipped_settings_are_in_the_flags_section`
- `test_d4_shared_vision_gate_is_on_with_shipped_settings`
- `test_d4_concurrent_jobs_stay_under_the_account_wide_vision_limit` (99 rejected calls with 4 jobs)

**Fix.**
- Moved the setting to `[flags]`.
- Made the default "on". The limit really is account-wide, so a missing setting shouldn't quietly fall back to per-job limits.
- Added a warning when any flag shows up outside `[flags]`.

**Numbers** (jobs of about 120 pages, all started at once):

| | 10 jobs: pages missing / calls rejected | 20 jobs: pages missing / calls rejected |
|---|---|---|
| Original | 241–248 of 1,235 (about 20%) / about 2,350 | 997 of 2,570 (39%) / 6,397 |
| Fixed | 0 / 0 | 0 / 0 |
| Fixed, but limiter forced off | 263 / 2,333 | 1,015 / 6,311 |

The last row is the giveaway. Turn just this one setting off and the losses come straight back.

**Why it looks like this.** With 10 jobs running, the service gets up to 100 calls at once and rejects most of them. Each rejected page retries 4 times. If it's still rejected, it's marked failed and left out of the total, but the job still says "complete". That's how you get a quietly low number.
- **Why at that scale, and why mornings.** One job alone is fine. The more jobs run together, the worse it gets, and people tend to upload at the start of the day.
- **Why ops saw green.** Jobs finish and nothing alerts on failed pages.
- **Why the tests missed it.** No test ran two jobs at once, and none read the real settings file.

**About "slow".** Locally this bug doesn't make jobs slower, because the retries fail fast. In production, retries back off for real, so I'd expect it to add delay on busy mornings. That part is a guess, not something I measured.

### D1: a retried page gets saved twice

**What's wrong.** Each saved result is keyed by job, page and a fresh ID that changes on every attempt. The worker saves the result, bumps the "pages done" count, and only then sends a progress update. That update fails about 4% of the time. When it does, the page is retried and saved again under a new key, and counted again.

**Tests.** `test_d1_a_failed_progress_event_does_not_count_the_page_twice` fails on the original. It stored 12 results for a 10-page job. `test_redelivered_page_is_stored_and_counted_once` fails too.

**Fix.**
- The key is now just job and page. The attempt ID still goes in the logs.
- Saving the result, bumping the count and marking the page done now happen together in one step, and only when a new result was actually saved.
- A page that was saved but whose progress update kept failing counts as done, not failed.
- Progress updates still go out exactly as before.

**One existing test was wrong.** `test_receipts_are_unique_per_invocation` checked that two tries at the same page get *different* keys. That's the bug. Catching the second try is the whole point of the key. I replaced it with `test_receipts_are_stable_across_deliveries`.

**Numbers.** On the original, the average error was +2.2% to +5.4% and the worst single run was +9% (one earlier run hit +10.1%). The extra saves grew with job size, from about 1 per run at 40 pages to about 21 at 500. On the fixed code there were zero extra saves and zero error at every size.

**Why it looks like this.**
- **Why "feels off".** The error is random, so the same set gives a different, too-high total each time. Nobody can point at one wrong number, but if you re-run or check by hand, you stop trusting it.
- **Who notices.** Everyone's affected, but big accounts see the most extra area and double-check the most.
- **Why ops saw green.** The progress bar is capped at 100%, so 125 out of 120 pages just showed as 100%.
- **Why the tests missed it.** Every job-level test switched progress updates off, which hid the only failure that happens after saving. One test even said the bug was correct.

### D2: failed pages don't count toward "finished"

**What's wrong.** A job counted as finished only when "pages done" equalled the page count. Failed pages weren't counted at all.

**Tests.** These fail on the original:
- `test_d2_job_with_an_unrenderable_page_settles_promptly`: a 100-page job ends up stuck.
- `test_d2_settled_accounts_for_failed_pages`.
- `test_d2_a_job_is_never_reported_complete_with_pages_outstanding`: the original said "complete" while page 10 was still running.

**Fix.** A job is finished when done plus failed equals the page count. I kept it as an exact match on purpose. Now that the counts are exact, an overcount should show up as "stuck", not get waved through. The old fallback runner uses the same check now, so rolling back won't bring the bug back.

**Numbers.**
- Jobs of 120, 250 and 500 pages: 15 of 15 got stuck and sat for the whole timeout on the original. That's 5 seconds with my test setting and 20 seconds in production. On the fixed code, all 15 finished in 0.07 to 0.23 seconds.
- Even 40- and 96-page jobs, which have no bad page, got stuck in 3 of 5 and 4 of 5 runs, because of D1.
- 4 of 5 jobs marked "complete" still had pages running. After the fix, that was 0 of 20.

**Why it looks like this.**
- **Why big sets.** One page in every 97 is deliberately broken, so any set of 97 pages or more has a page that can't finish. "Pages done" never reaches the page count, and the job always waits out the full timeout. That's the slow part of the complaint.
- **Why numbers change after "complete".** Add D1's duplicate saves and the count can hit the target exactly while pages are still running. The job says "complete" too early, and the total keeps changing afterwards.
- **Why the tests missed it.** The only full-job test used 8 pages with progress updates switched off.

### D3: the cache hands back another scale's numbers

**What's wrong.** The cache key was the set's fingerprint plus the page number, and the fingerprint only used sheet size and page count. Scale wasn't in it, even though the README says scale is part of what defines a set.

**Tests.** `test_d3_memo_key_differs_when_the_drawing_scale_differs` and `test_d3_resubmitting_a_set_at_a_new_scale_gets_new_measurements` fail on the original.

**Fix.**
- The cache is now keyed on a hash of the page itself. That matches how the measuring service works: same page, same number. A different page can never get someone else's result, and a true re-upload still hits the cache.
- The key starts with `v2:`, so old entries still sitting in the production cache won't be used.
- I also added scale to the fingerprint.

**Numbers.** I ran a 40-page set at scale 48, then again at scale 96. The original reported 9,397.14 instead of the true 8,801.79, which is 6.76% off and is just the scale-48 total again. The fixed code reported 8,801.79 exactly.

**Why it looks like this.** It hits people who fix a wrong scale and re-run within the hour, which is the cache's lifetime. They get the same number back, which is about the worst thing a measuring tool can do. The tests only checked that the same set gets the same key, never that different sets get different keys.

### D5: sheet labels repeat in sets over 199 pages

**What's wrong.** The number in each sheet label wrapped around at 99 while each letter series holds 100 sheets. So page 199 got the same label as page 100 (`B-01`), and the same thing happened at 299, 399 and 499. Same label means the same page content, so those pages got another page's measurement.

**Test.** `test_d5_every_page_of_a_full_size_set_is_a_distinct_drawing` fails on the original.

**Fix.** The number is now the page's position within its series, which is what the code comment says it should be. Series A is pages 1 to 99, since there's no page 0, and series B is pages 100 to 199. Both examples in the comment still hold: page 1 is `A-01` and page 150 is `B-51`.

**Heads-up.** This changes 304 of 500 labels, and so their numbers. Those labels were wrong by the code's own description, not just the 4 that collided. Sets over 200 pages will show different numbers when re-run, and the customer note says so.

**Numbers.** 4 pages per 500-page set shared content with an earlier page. Now it's 0.

**Caveat.** This renderer stands in for real PDF processing. I can't see whether production has the same problem.

### D6: timestamps are 6 hours off

**What's wrong.** Times were saved in Chicago local time and then sent out with a "Z" (UTC) tag, without being converted.

**Test.** `test_d6_api_timestamps_are_actually_utc` fails on the original.

**Fix.** Times are now saved in UTC. Older rows saved in local time get converted properly when read.

**Numbers.** Off by −6.0 hours before, 0 after. It was 5 hours before daylight saving ended on Nov 1.

**Impact.** No numbers change. It just makes "when did this run?" wrong, and local times sort badly around the daylight saving switch. The old test only checked that the string ended in "Z".

### D7: closing the database while it's still writing (local only)

The original test run crashed with a segfault while I was reproducing D2. A test finished, closed the database, and a page was still writing to it.

`close()` now waits for any write in progress. `test_d7_closing_the_database_waits_for_an_in_flight_write` fails on the original. This doesn't affect production, which uses DynamoDB, but it crashed the original test run, so I've listed it.

### D8: the Lambda-style handler never gets a rate limiter

`lambda_handler` read its rate limiter from the incoming event. A real Lambda event is plain JSON and can't carry one, so the limiter was always empty and the handler crashed with a `TypeError` whenever the cache missed. It now falls back to the shared limiter. `test_d8_lambda_handler_works_with_a_json_only_event` fails on the original. Nothing in the local setup calls this handler, but it's the shape the deployed service uses.

---

## Things I checked that turned out fine

| What I looked at | Why it looked wrong | Why it's fine |
|---|---|---|
| `increment_done` reads, then writes | Looks like two threads could clash | Both steps run under one lock. The existing test gets exactly 800 of 800 with 32 threads. |
| `legacy_runner._bump_done` | Same pattern with no lock | Nothing calls it, and the fallback runner is switched off. I only pointed the runner's finish and fail checks at the fixed code. |
| `0.09290304` in the unit conversion | Looks like a magic number | It's exactly 0.3048², the definition of a square foot in square metres. |
| Retry backoff | Random jitter might go past the cap | Jitter is 0.5x to 1.5x of the capped value, so it stays bounded. The test gives 0.1, 0.2, 0.4, 0.5, 0.5, 0.5. |
| 0.25-second job status cache | Could show a stale status | It's very short, and `wait()` clears it before reading. |
| Cache expiry | Clock changes could break it | It uses a monotonic clock, so wall-clock and daylight saving changes don't matter. |
| Measuring-service error handling | Could swallow errors | Throttles and timeouts are retried, and anything else is passed up. That's right for a service we don't own. |
| Every 97th page fails | Looks like a bug | It's intentional, per the README. It models corrupt pages. The bug was in how finishing treated them (D2). |
| The homemade settings parser | Homemade parsers often break | It handles `#` inside quotes and the value types the file uses, and its test passes. |
| Database "locked" retry loop | Could loop forever | It stops after 5 tries, and one shared connection never gets locked anyway. |
| Per-job limit of 10, the same as the account limit | Looks like the bug itself | It's fine for one job. The bug is using per-job limits at all when several jobs run (D4). |
| Progress bar capped at 100% | Hides overcounts | That's a reasonable display rule. It hid D1, but it isn't wrong, so I kept it. |
| `int(float(str(x)))` for page counts | "120.7" quietly becomes 120 | Sloppy, but real clients send whole numbers. Noted, not changed. |
| Database migrations | Ignore errors | They only ignore "column already exists", and the local setup never runs them. |

---

## Production: the shared limit, and what changes in Lambda

**Keeping the account to 10 calls across every job and environment.** Once each page runs in its own Lambda, an in-memory limit does nothing, because each Lambda has its own memory. I'd use a small DynamoDB table of 10 "slots" that every environment shares:
1. To call the service, a worker claims a free slot with a conditional write: "only if nobody holds it, or the last holder's claim has expired".
2. When it's done, it releases the slot, but only if it's still the holder.
3. Each claim expires a little after the service's timeout, so a Lambda that crashes doesn't block a slot forever.
4. If no slot is free, the worker raises an error that Step Functions retries with backoff. Waiting that way doesn't cost Lambda time.
5. I'd give test environments a small fixed share, say 2 of the 10, so a load test can't throttle customers.
6. I'd keep the existing handling for rejected calls as a backup.

**What each local fix becomes in Lambda:**

| Local fix | In Lambda and DynamoDB |
|---|---|
| D4/D8: in-memory shared limiter | The slot table above |
| D1: one key per page, save and count in one step | Key results on job and page. Save with "only if it doesn't exist" and bump the count in the same DynamoDB transaction. If the save is refused, the page is already done. |
| D1: don't count a saved page as failed | In the same transaction, check there's no result, then bump the failed count |
| D2: finished when done plus failed equals total | Let the Map state decide. It ends when every page has finished or been caught. The counters then only drive the progress bar. |
| D3: cache keyed on the page content | A DynamoDB table keyed on a hash of the page image, with an expiry time |
| D6: save times in UTC | No change |
| D7: lock on close | Doesn't apply |

**Cleaning up old data.** Jobs saved before the fix still have duplicate rows. Find results with more than one row for the same job and page, recompute those totals, and give customer success the list of affected jobs with corrected numbers.

---

## Note for customer success

> **Subject: Why your takeoff totals felt off, and what we fixed**
>
> Thanks for telling us the recent totals felt off. You were right, and we found out why.
>
> **What was going wrong**
> - **Some pages were counted twice.** When part of our system had a brief hiccup, it sometimes measured a page again and added it a second time. Totals came out a few percent too high, usually 2 to 5 percent and sometimes up to about 10. It changed from run to run, so the same plans could give different answers.
> - **Some pages were left out on busy mornings.** A safety setting that stops us overloading our measuring service was accidentally switched off in a recent update. When lots of plans were processed at once, some pages couldn't be measured and were quietly left out, so totals came out too low.
> - **Fixing the drawing scale didn't always work.** If you re-ran a set within an hour of correcting its scale, you could get the old numbers back.
> - **A few pages in very large sets** (around 200 pages or more) were mixed up and showed another page's measurement.
> - **Large sets were slow to finish,** and sometimes showed as done before every page was measured.
>
> **What we've done**
> All of this is fixed. In our testing, every total now matches a page-by-page check exactly, including large sets and busy times.
>
> **What this means for you**
> - **You can trust new runs.** If you re-run a recent set, the number may be different from before. The new one is right.
> - **Sets over 200 pages** may change more than smaller ones, because some of their pages were being mixed up.
> - **Older results.** We're going through recent jobs to find the affected ones, and we can send you corrected totals. Just tell us which projects matter most.
>
> Sorry for the confusion, and thanks for flagging it.

---

## How sure I am, and what's left

**What I'm sure of.** These eight bugs are real, they're fixed, and together they explain the complaint:
- Too high: D1.
- Too low on busy mornings: D4.
- "Feels" off, because it changes from run to run: D1, D2 and D4.
- A corrected re-run gives the same number: D3.
- Slow: D2, which I measured, and D4, which I expect but didn't measure.
- Ops sees green: jobs finish, the progress bar caps at 100%, and nothing alerts on failed pages.

The full-job ground-truth test and the evidence runs found no errors left in the fixed code. I'm fairly confident that's everything in the local copy. I can't be sure about production, because I can't see its code.

**What I suspect but can't prove:**
1. **Production might mix up different customers' drawings.** The set fingerprint never looked at the actual PDF, only sheet size, page count and now scale. Locally, that fully describes a set. In production, two different customers' 120-page ARCH_D sets at the same scale would share cached numbers for an hour. Keying the cache on page content (the D3 fix) closes this, but I can't show it locally. It's the first thing I'd check in production.
2. **Which bugs came from the release.** D4 fits "a config change about a month ago" well. D1, D2 and D5 look much older, since the test that hid D1 has passed for months. There's no history to confirm either way.
3. **D4 slowing production down.** As covered under D4, that's an educated guess, not a measurement.
4. **Silent crashes in worker threads.** If a worker throws an error that isn't one of the pipeline's own error types, the thread pool swallows it, the page never finishes and the job gets stuck. I never saw it happen, so I didn't change it.

**What I'd look at next:**
- In production: rejected calls and failed pages by hour, and cache hit rates by account, including whether any cache key is shared between accounts.
- The real Parameter Store values for `shared_gate`.
- A count of duplicate results over the last 60 days, to see how big the damage is per account.

**What would change my mind.** Production reads settings from AWS Parameter Store, not from this `settings.toml`. If Parameter Store has `shared_gate` in the right place, D4 is only a local mistake and isn't what's happening in production. In that case, rejected calls should be flat on slow mornings, and I'd look for the slowness somewhere else, like cold starts or slow reads while checking whether a job is finished.

---

## What I changed

- **Fixes:**
  - Result keys and saving: [ids.py](takeoff/core/ids.py), [models.py](takeoff/core/models.py), [repo_results.py](takeoff/storage/repo_results.py), [repo_jobs.py](takeoff/storage/repo_jobs.py), [db.py](takeoff/storage/db.py)
  - Workers and scheduling: [page_worker.py](takeoff/workers/page_worker.py), [render.py](takeoff/workers/render.py), [handler.py](takeoff/workers/handler.py), [completion.py](takeoff/scheduler/completion.py), [dispatcher.py](takeoff/scheduler/dispatcher.py), [legacy_runner.py](takeoff/scheduler/legacy_runner.py)
  - Cache, API, clock and config: [memo.py](takeoff/cache/memo.py), [schemas.py](takeoff/api/schemas.py), [serializers.py](takeoff/api/serializers.py), [clock.py](takeoff/core/clock.py), [flags.py](takeoff/config/flags.py), [defaults.py](takeoff/config/defaults.py), [settings.toml](settings.toml)
- **Tests:** [tests/test_regressions.py](tests/test_regressions.py) is new. In [tests/test_worker.py](tests/test_worker.py) I fixed one wrong test and added one.
- **Tools:** [scripts/evidence.py](scripts/evidence.py), [scripts/before_after.sh](scripts/before_after.sh), and the saved output in [evidence/before_after.txt](evidence/before_after.txt).
- **Not touched:** `takeoff/services/vision.py`. Every entry point in the README still works the same way.
