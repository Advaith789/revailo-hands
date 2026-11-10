# Part 2: cloud proof

| | |
|---|---|
| **Region** | `us-east-2` |
| **Run (UTC)** | 2026-11-10T18:06:24Z (apply) to about 18:08Z (destroy verified) |
| **Account** | Redacted as `<account-id>` in all output |
| **Caller** | IAM user `terraform-demo`, created for this run and deleted afterwards |
| **Tools** | Terraform v1.17.1, AWS provider `~> 6.0`, aws-cli 1.46.3 |
| **Full logs** | [proof/run-20261110T180623Z.log](proof/run-20261110T180623Z.log) is the passing run. [proof/run-20261110T180407Z.log](proof/run-20261110T180407Z.log) is the first, failed run (see section 5). |

## What is deployed

All of it is created by the Terraform in this directory (9 resources):

- **`aws_sfn_state_machine.pages`:** a Standard state machine. A `Map` over `$.pages` (MaxConcurrency 3) runs one `lambda:invoke` task per page. Each item gets `job_id`, `page_no` and the execution name. Only transient Lambda-service errors are retried, with exponential backoff and full jitter.
- **`aws_lambda_function.worker`:** Python 3.13 on arm64 ([lambda/worker.py](lambda/worker.py)). It writes `area_sqft = page_no * 10` with `PutItem` and the condition `attribute_not_exists(job_id)`. If the row already exists, the worker returns `stored: false` and succeeds, so a replay can neither add a row nor change one.
- **`aws_dynamodb_table.results`:** on-demand capacity, partition key `job_id` (S), sort key `page_no` (N). It is read with `Query` by `job_id`, never with `Scan`.
- **`aws_cloudwatch_log_group.worker`:** the worker's log group, managed by Terraform with 1-day retention. It is created before the function, so Lambda never creates an unmanaged one.
- **IAM roles:**
  - The worker role can only `dynamodb:PutItem` on the one table, and `logs:CreateLogStream`/`PutLogEvents` on the one log group.
  - The state machine role can only `lambda:InvokeFunction` on the one function and its versions. Its trust policy is limited by `aws:SourceAccount`.
- **`time_sleep.iam_propagation`:** a 15-second wait for IAM propagation before the state machine is created (see section 5).
- **Outputs:** `state_machine_arn` and `table_name`.

Nothing in the stack costs money while idle: no VPC, NAT, EC2, RDS or provisioned concurrency.

The worker's logic is also covered locally: run `cd cloud/lambda && python -m pytest`. That gives 8 passed, using an in-memory stand-in for DynamoDB's conditional put.

## How to reproduce

You need AWS credentials and Terraform 1.6 or later. One command does everything below and writes a redacted log to `cloud/proof/`:

```bash
cloud/prove.sh
```

`prove.sh` runs these steps in order, and it destroys the stack even if the smoke test fails:
1. `terraform init`
2. `terraform fmt -check -recursive`
3. `terraform validate`
4. `terraform apply -auto-approve`
5. `./smoke.sh`
6. `terraform destroy -auto-approve`
7. `./verify_destroyed.sh`

The individual pieces:

```bash
cd cloud
terraform init && terraform apply
./smoke.sh                       # two executions, same job id; exits non-zero on any mismatch
JOB_ID=my-job ./smoke.sh         # choose the job id
terraform destroy
./verify_destroyed.sh            # exits non-zero if anything remains
```

## 1. Region and timestamp

```
================ context
UTC: 2026-11-10T18:06:24Z
Terraform v1.17.1
aws-cli/1.46.3 Python/3.12.12 Darwin/25.5.0 botocore/1.43.62
arn:aws:iam::<account-id>:user/terraform-demo
```

## 2. fmt, validate, apply, and the execution reaching SUCCEEDED

```
$ terraform fmt -check -recursive
fmt: OK (no changes needed)

$ terraform validate
Success! The configuration is valid.

$ terraform apply -input=false -auto-approve
aws_cloudwatch_log_group.worker: Creation complete after 0s [id=/aws/lambda/revailo-takeoff-demo-worker]
aws_iam_role.worker: Creation complete after 0s [id=revailo-takeoff-demo-worker]
aws_iam_role.sfn: Creation complete after 0s [id=revailo-takeoff-demo-sfn]
aws_dynamodb_table.results: Creation complete after 8s [id=revailo-takeoff-demo-results]
aws_iam_role_policy.worker: Creation complete after 0s [id=revailo-takeoff-demo-worker:revailo-takeoff-demo-worker]
aws_lambda_function.worker: Creation complete after 6s [id=revailo-takeoff-demo-worker]
aws_iam_role_policy.sfn: Creation complete after 1s [id=revailo-takeoff-demo-sfn:revailo-takeoff-demo-sfn]
time_sleep.iam_propagation: Creation complete after 15s [id=2026-11-10T18:07:00Z]
aws_sfn_state_machine.pages: Creation complete after 1s [id=arn:aws:states:us-east-2:<account-id>:stateMachine:revailo-takeoff-demo-pages]
Apply complete! Resources: 9 added, 0 changed, 0 destroyed.

Outputs:
region = "us-east-2"
state_machine_arn = "arn:aws:states:us-east-2:<account-id>:stateMachine:revailo-takeoff-demo-pages"
table_name = "revailo-takeoff-demo-results"
```

First execution. The start and stop times print as epoch seconds; in UTC they are 18:07:04.055Z and 18:07:07.524Z.

```
$ aws stepfunctions start-execution --state-machine-arn <state_machine_arn> \
    --name smoke-20261110T180703Z-run1-180703 \
    --input '{"job_id":"smoke-20261110T180703Z","pages":[1,2,3]}'
$ aws stepfunctions describe-execution --execution-arn <arn> --query '[name,status,startDate,stopDate]'
smoke-20261110T180703Z-run1-180703	SUCCEEDED	1794334024.055	1794334027.524
$ aws stepfunctions describe-execution --execution-arn <arn> --query output
{"job_id":"smoke-20261110T180703Z","pages":[1,2,3],"results":[
  {"job_id":"smoke-20261110T180703Z","page_no":1,"area_sqft":10,"stored":true},
  {"job_id":"smoke-20261110T180703Z","page_no":2,"area_sqft":20,"stored":true},
  {"job_id":"smoke-20261110T180703Z","page_no":3,"area_sqft":30,"stored":true}]}
```

## 3. Table contents after the first execution and after the replay

After the first execution:

```
$ aws dynamodb query --table-name revailo-takeoff-demo-results --consistent-read \
    --key-condition-expression 'job_id = :j' \
    --expression-attribute-values '{":j":{"S":"smoke-20261110T180703Z"}}' \
    --query 'Items[].[job_id.S,page_no.N,area_sqft.N,first_execution.S]' --output table
+-------------------------+----+-----+--------------------------------------+
|  smoke-20261110T180703Z |  1 |  10 |  smoke-20261110T180703Z-run1-180703  |
|  smoke-20261110T180703Z |  2 |  20 |  smoke-20261110T180703Z-run1-180703  |
|  smoke-20261110T180703Z |  3 |  30 |  smoke-20261110T180703Z-run1-180703  |
+-------------------------+----+-----+--------------------------------------+
OK (after first execution): exactly 3 rows, areas 10/20/30
```

The replay used a **new execution name** and the **same job ID**:

```
$ aws stepfunctions start-execution --state-machine-arn <state_machine_arn> \
    --name smoke-20261110T180703Z-replay-180711 \
    --input '{"job_id":"smoke-20261110T180703Z","pages":[1,2,3]}'
$ aws stepfunctions describe-execution --execution-arn <arn> --query '[name,status,startDate,stopDate]'
smoke-20261110T180703Z-replay-180711	SUCCEEDED	1794334032.052	1794334032.209
$ aws stepfunctions describe-execution --execution-arn <arn> --query output
{"job_id":"smoke-20261110T180703Z","pages":[1,2,3],"results":[
  {"job_id":"smoke-20261110T180703Z","page_no":1,"area_sqft":10,"stored":false},
  {"job_id":"smoke-20261110T180703Z","page_no":2,"area_sqft":20,"stored":false},
  {"job_id":"smoke-20261110T180703Z","page_no":3,"area_sqft":30,"stored":false}]}

$ aws dynamodb query ... (same command as above)
+-------------------------+----+-----+--------------------------------------+
|  smoke-20261110T180703Z |  1 |  10 |  smoke-20261110T180703Z-run1-180703  |
|  smoke-20261110T180703Z |  2 |  20 |  smoke-20261110T180703Z-run1-180703  |
|  smoke-20261110T180703Z |  3 |  30 |  smoke-20261110T180703Z-run1-180703  |
+-------------------------+----+-----+--------------------------------------+
OK (after replay with same job id, new execution name): exactly 3 rows, areas 10/20/30
```

The replay succeeded with `stored: false` for every page. The table still has exactly three rows with the same values, and `first_execution` still names run 1, which shows the replay did not overwrite anything. `smoke.sh` compares the query result to exactly `1→10, 2→20, 3→30` and exits non-zero otherwise. Here it exited 0.

## 4. Destroy and the final check

```
$ terraform destroy -input=false -auto-approve
...
Destroy complete! Resources: 9 destroyed.

$ ./verify_destroyed.sh
$ terraform state list
(empty)
gone: DynamoDB table revailo-takeoff-demo-results -> ResourceNotFoundException
gone: Lambda revailo-takeoff-demo-worker -> ResourceNotFoundException
gone: State machine revailo-takeoff-demo-pages -> StateMachineDoesNotExist
gone: IAM role revailo-takeoff-demo-worker -> NoSuchEntity
gone: IAM role revailo-takeoff-demo-sfn -> NoSuchEntity
gone: log group /aws/lambda/revailo-takeoff-demo-worker -> (no match)

smoke exit=0  verify_destroyed exit=0
```

The `terraform-demo` IAM user and its access key were created by hand for this run, outside Terraform, and then deleted.

## 5. What I could not verify, and the next failure mode to test

**A failure that actually happened.** The first `prove.sh` run ([proof/run-20261110T180407Z.log](proof/run-20261110T180407Z.log)) applied cleanly. Then the first execution failed about 2 seconds after the state machine was created:

```
Lambda.AWSLambdaException  User: arn:aws:sts::<account-id>:assumed-role/revailo-takeoff-demo-sfn/... is not
authorized to perform: lambda:InvokeFunction on resource: arn:aws:lambda:us-east-2:<account-id>:function:revailo-takeoff-demo-worker
because no identity-based policy allows the lambda:InvokeFunction action (... Status Code: 403 ...)
```

The policy allowed exactly that ARN, but IAM is eventually consistent and the new inline policy hadn't propagated yet. The script still destroyed the stack and confirmed it was gone.

**The fix.** A `time_sleep` of 15 seconds after both role policies, before the state machine is created. I deliberately did **not** add `AccessDenied` to the state machine's `Retry`, because that would also hide real permission mistakes. The second run passed.

**What I could not verify:**
- **Retries of the same execution.** The replay test reruns the whole job under a new execution name. I didn't force a Lambda-service error mid-Map to watch Step Functions' own `Retry` redeliver a page within the same execution. The conditional put makes that safe by construction, and the local unit test `test_replay_succeeds_without_changing_the_row` covers the logic, but it wasn't observed in AWS.
- **Concurrent first writes.** I didn't test two executions racing on the same job at the same moment. DynamoDB conditional writes are atomic per item, so exactly one write should win, but I didn't observe it.
- **Cost.** Not measured directly. The stack existed for about 2 minutes, and everything in it is on-demand.
- **The 15-second wait.** It is a timing-based mitigation, not a guarantee. IAM propagation has no hard upper bound.

**The next failure mode I'd test: a page whose processing fails permanently.** A bad page (here, an invalid `page_no`; in production, the corrupt pages from Part 1) raises an error that is not retried. That fails the `Map`, and so the **whole execution**, so the other pages' results are stored but the job looks failed. The test would send `{"job_id":"x","pages":[1,0,3]}`. I'd expect `FAILED` with rows only for 1 and 3. I'd then decide between a per-item `Catch` that records the page as failed, or a `ToleratedFailurePercentage`, so a single bad page doesn't fail a 500-page job. This is the cloud version of Part 1's D2.

## Shared vision limit and Lambda-specific mechanisms

The `Map` `MaxConcurrency` here limits one execution only. How I'd enforce the account-wide limit of ten calls across jobs and environments, and which of my Part 1 fixes need a different mechanism once each page runs in its own Lambda, is covered in [takeoff-pipeline/REPORT.md](../takeoff-pipeline/REPORT.md#production-the-shared-vision-limit-and-which-local-fixes-need-a-different-mechanism).

## Not submitted

No `.terraform/`, Terraform state, build zips or credentials. All are in `.gitignore`, and the logs are redacted. `.terraform.lock.hcl` *is* committed, so provider versions are pinned.
