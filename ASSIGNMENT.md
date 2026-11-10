# Revailo - Cloud Software Engineer coding test

Two parts. **Part 1** is a debugging investigation on the code in this repository. **Part 2** is a small, separate deployment on AWS. They are not connected; do them in either order.

# Part 1 - The escalation

## Context

`takeoff-pipeline/` is a local reproduction of a service of ours. Estimators upload construction plan sets (1 to 500 pages) and we measure every page. The real thing runs on Step Functions and Lambda against DynamoDB; this is the same control flow with the cloud parts swapped for in-process equivalents. Read `takeoff-pipeline/README.md` first. The test suite passes, and has done for months.

## The complaint

Pasted from the customer-success channel on Thursday:

> Not a ticket exactly. A few of the larger accounts have said over the last month or so that the takeoff numbers "feel off". Nobody has given us a job ID or a number they can point to, they just say they trust it less than they used to. Two of them also said the app is slow some mornings and fine other times. Ops says everything is green and the dashboards look normal. A release went out around then, but ops says it was all config and plumbing, nothing that touches the math. Can engineering take a look?

That is the whole report. Nobody is available for follow-up questions, and there are no job IDs to pull.

## What to do

Work out what is actually going on, prove it, and fix it.

We will not tell you how many defects there are. There may be one cause behind several symptoms, several causes behind one symptom, and problems the complaint does not mention at all. Rank what you find by customer impact.

For each problem you find:

1. **Reproduce it.** A test that fails against the code as it stands.
2. **Fix it.**
3. **Explain why it manifests the way it does.** Why that symptom, why at that scale, why some customers and not others, and why the existing test suite never caught it. A short paragraph each.

Include exact commands for running your tests against the original and fixed code, plus one observed before/after result for each claim. A claim without a number next to it is a hypothesis, and we score it as one.

Also include a **Ruled out** section: things you looked at that turned out to be fine, and the evidence that satisfied you. We score correct dismissals; code that looks wrong but is not is part of every real codebase.

Then write the note customer success can send to the accounts that complained: plain language, no jargon. They have to decide whether to trust the next number.

Finish with an honest statement of how confident you are that you found everything, anything you suspect but could not prove, and what you would look at next. Name one observation that would make you change your diagnosis.

## Ground rules for Part 1

**Do not modify `takeoff/services/vision.py`.** It models a dependency we do not own.

**The test suite is not an oracle.** It passes. If you conclude a test asserts the wrong thing, say so, change it, and explain why in your report.

**Turning a feature off is not a fix** unless you argue the feature should not exist. The memo, the progress events and the flags are there for reasons that are written down next to them.

**Keep the entry points listed in `takeoff-pipeline/README.md` working.** Our checks drive the code through them.

# Part 2 - Deploy a small workflow on AWS

Separate from Part 1 and much smaller. This is a proof that you can work with AWS resources, not a request to recreate the production system. Run it on AWS with Terraform. Keep it deliberately small and stop when you reach the overall time budget.

You will need Terraform and the AWS CLI or an SDK for the smoke run.

## Behavior to demonstrate

Create all resources with Terraform. A Step Functions **Standard** state machine accepts input shaped like `{"job_id":"your-unique-job-id","pages":[1,2,3]}` and uses a `Map` state to invoke a Lambda worker for each page. The worker writes one result per `(job_id, page_no)` into a DynamoDB table. Use a deterministic stand-in measurement: `area_sqft = page_no * 10`. You do not need to call a real measuring service, render PDFs, build an API, or build a frontend.

Run the workflow once and show that the execution succeeds and the table contains exactly three page results with areas 10, 20 and 30. Run it again with a **new Step Functions execution name but the same job ID** and show that the table still has exactly those three results. Query the table by that job ID rather than relying on a whole-table scan. A retry or repeated execution must not add extra rows or change their values. You may choose how to handle an already-present result, but the execution should still finish successfully.

Your Terraform should create the state machine, Lambda function, DynamoDB table, and the IAM roles and permissions they need. Scope permissions to the resources they use. Output the state machine ARN and table name. Manage everything, including any log group you create, through Terraform. Use DynamoDB on-demand capacity, and avoid VPCs, NAT gateways, RDS, EC2, provisioned concurrency or anything else that accrues charges while idle - this workload should cost very little and should not be left running.

The `Map` concurrency setting in this small demo is **not** a solution to the measuring service's account-wide ten-call limit. In your Part 1 report, say how you would enforce that shared limit across other jobs and application environments, and which of your local fixes would need a different mechanism once each page runs in its own Lambda. Do not build a distributed limiter for this part.

## Evidence to submit

Put the Terraform, Lambda code, and a repeatable smoke script or exact AWS CLI commands in a `cloud/` directory. Add `cloud/CLOUD-PROOF.md` containing:

1. The AWS Region and a UTC timestamp. Redact account IDs if you wish.
2. The commands and relevant output for `terraform fmt -check`, `terraform validate`, `terraform apply`, and the execution reaching `SUCCEEDED`.
3. The command and output showing the three DynamoDB rows after the first execution, and again after the replay with the same job ID.
4. The commands and output for `terraform destroy`, and a final check that the Terraform-managed resources are gone.
5. What you could not verify, and one cloud failure mode you would test next.

Screenshots are welcome as supporting evidence but are not enough on their own - include reproducible commands so we can check the behavior. Never submit AWS access keys, secret values, `.terraform/` or Terraform state files.

Destroy the stack once you have your evidence.

# Ground rules for both parts

**AI tools.** Use them. We do. You will be asked to explain any line of what you submit, including lines a model wrote, and in a later session to debug this codebase live. Do not ship a fix you cannot explain.

**If something blocks you** - a permission, a quota, an error you cannot get past - send us the exact error promptly rather than working around it.

**If you suspect something and cannot prove it, say so** rather than leaving it out. We score that honestly and it is not a penalty.


