# Part 2: proof it ran on AWS

| | |
|---|---|
| **Region** | `us-east-2` |
| **When (UTC)** | 2026-11-10, deployed at 18:06:24, torn down and checked by about 18:08 |
| **Account** | Hidden. Every account number in the output shows as `<account-id>`. |
| **Who ran it** | An IAM user called `terraform-demo`, made just for this and deleted afterwards |
| **Tools** | Terraform 1.17.1, AWS provider 6.x, AWS CLI 1.46.3 |
| **Full logs** | [proof/run-20261110T180623Z.log](proof/run-20261110T180623Z.log) is the run that passed. [proof/run-20261110T180407Z.log](proof/run-20261110T180407Z.log) is the first run, which failed (see section 5). |

## What gets built

Terraform creates all of it, 9 resources in total:

- **A Standard Step Functions state machine.** A Map step goes over `pages` and calls the worker Lambda once per page, up to 3 at a time. Each call gets the job ID, the page number and the execution name. It only retries short-lived Lambda service errors.
- **The worker Lambda** (Python 3.13, [lambda/worker.py](lambda/worker.py)). It writes `area_sqft = page_no * 10` using "only save if this row doesn't exist yet". If the row's already there, it returns `stored: false` and still succeeds. So running the job again can't add a row or change one.
- **A DynamoDB table** with on-demand billing, keyed on `job_id` and then `page_no`. I read it with a query by job ID, never a full table scan.
- **The Lambda's log group,** made by Terraform with 1-day retention. It's created before the Lambda so AWS doesn't make its own unmanaged one.
- **Two IAM roles, each limited to one resource.** The Lambda can only write to this one table and its own log group. The state machine can only call this one Lambda.
- **A 15-second wait** before the state machine is created, so IAM has time to catch up. Section 5 explains why.

Nothing here costs money while it sits idle: no VPC, NAT, EC2, RDS or reserved capacity.

I also tested the worker locally with a fake table: run `cd cloud/lambda && python -m pytest`, which gives 8 passed.

## Run it yourself

You need AWS credentials and Terraform 1.6 or newer. One command does everything and saves a log to `cloud/proof/` with the account number hidden:

```bash
cloud/prove.sh
```

It runs init, fmt-check, validate, apply, the smoke test, destroy, and a final "is it all gone" check. It tears the stack down even if the smoke test fails.

Or step by step:

```bash
cd cloud
terraform init && terraform apply
./smoke.sh                  # two runs with the same job ID; fails loudly on any mismatch
JOB_ID=my-job ./smoke.sh    # pick your own job ID
terraform destroy
./verify_destroyed.sh       # fails if anything is left behind
```

## 1. Region and time

```
================ context
UTC: 2026-11-10T18:06:24Z
Terraform v1.17.1
aws-cli/1.46.3 Python/3.12.12 Darwin/25.5.0 botocore/1.43.62
arn:aws:iam::<account-id>:user/terraform-demo
```

## 2. fmt, validate, apply, and the run reaching SUCCEEDED

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

The first run is below. The start and stop times print as seconds since 1970; in UTC that's 18:07:04.055 to 18:07:07.524. `$SM_ARN` is the `state_machine_arn` output above, and `$EXEC_ARN` is the execution ARN that `start-execution` returns.

```
$ aws stepfunctions start-execution --state-machine-arn "$SM_ARN" \
    --name smoke-20261110T180703Z-run1-180703 \
    --input '{"job_id":"smoke-20261110T180703Z","pages":[1,2,3]}'
$ aws stepfunctions describe-execution --execution-arn "$EXEC_ARN" --query '[name,status,startDate,stopDate]'
smoke-20261110T180703Z-run1-180703	SUCCEEDED	1794334024.055	1794334027.524
$ aws stepfunctions describe-execution --execution-arn "$EXEC_ARN" --query output
{"job_id":"smoke-20261110T180703Z","pages":[1,2,3],"results":[
  {"job_id":"smoke-20261110T180703Z","page_no":1,"area_sqft":10,"stored":true},
  {"job_id":"smoke-20261110T180703Z","page_no":2,"area_sqft":20,"stored":true},
  {"job_id":"smoke-20261110T180703Z","page_no":3,"area_sqft":30,"stored":true}]}
```

## 3. The table after the first run and after the replay

After the first run:

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

Then the replay, with a new execution name and the same job ID:

```
$ aws stepfunctions start-execution --state-machine-arn "$SM_ARN" \
    --name smoke-20261110T180703Z-replay-180711 \
    --input '{"job_id":"smoke-20261110T180703Z","pages":[1,2,3]}'
$ aws stepfunctions describe-execution --execution-arn "$EXEC_ARN" --query '[name,status,startDate,stopDate]'
smoke-20261110T180703Z-replay-180711	SUCCEEDED	1794334032.052	1794334032.209
$ aws stepfunctions describe-execution --execution-arn "$EXEC_ARN" --query output
{"job_id":"smoke-20261110T180703Z","pages":[1,2,3],"results":[
  {"job_id":"smoke-20261110T180703Z","page_no":1,"area_sqft":10,"stored":false},
  {"job_id":"smoke-20261110T180703Z","page_no":2,"area_sqft":20,"stored":false},
  {"job_id":"smoke-20261110T180703Z","page_no":3,"area_sqft":30,"stored":false}]}

$ aws dynamodb query ...   (same query as above)
+-------------------------+----+-----+--------------------------------------+
|  smoke-20261110T180703Z |  1 |  10 |  smoke-20261110T180703Z-run1-180703  |
|  smoke-20261110T180703Z |  2 |  20 |  smoke-20261110T180703Z-run1-180703  |
|  smoke-20261110T180703Z |  3 |  30 |  smoke-20261110T180703Z-run1-180703  |
+-------------------------+----+-----+--------------------------------------+
OK (after replay with same job id, new execution name): exactly 3 rows, areas 10/20/30
```

The replay succeeded, and every page said `stored: false`. The table still has the same three rows with the same values. The last column still shows run 1 as the writer, so the replay didn't overwrite anything. `smoke.sh` checks for exactly 1→10, 2→20, 3→30 and fails if it sees anything else. Here it passed.

## 4. Tear-down and the final check

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

I made the `terraform-demo` user and its access key by hand, outside Terraform, and deleted them after the run.

## 5. What I couldn't check, and what I'd test next

**The first run failed, and I kept the log.** In [proof/run-20261110T180407Z.log](proof/run-20261110T180407Z.log), everything deployed fine, but the first execution failed about 2 seconds after the state machine was created:

```
Lambda.AWSLambdaException  User: arn:aws:sts::<account-id>:assumed-role/revailo-takeoff-demo-sfn/... is not
authorized to perform: lambda:InvokeFunction on resource: arn:aws:lambda:us-east-2:<account-id>:function:revailo-takeoff-demo-worker
because no identity-based policy allows the lambda:InvokeFunction action (... Status Code: 403 ...)
```

The permission was correct. IAM just hadn't caught up yet, because new permissions take a few seconds to reach every part of AWS. The script still tore everything down and confirmed it was gone.

**The fix.** Terraform now waits 15 seconds after creating the permissions, before it builds the state machine. I didn't make the state machine retry on "access denied", because that would also hide real permission mistakes. The second run passed.

**What I couldn't check:**
- **A retry inside a single run.** I didn't force a Lambda error partway through to watch Step Functions retry a page within the same run. The "only save if it doesn't exist" rule should make that safe, and the local unit test covers it, but I didn't see it happen on AWS.
- **Two runs racing.** I didn't start two runs for the same job at the exact same moment. DynamoDB should let exactly one write win, but I didn't watch it happen.
- **Cost.** I didn't measure it. The stack was up for about 2 minutes, and everything is pay-per-use.
- **The 15-second wait.** It's a timing fix, not a guarantee. AWS doesn't promise how long IAM takes to catch up.

**What I'd test next: one bad page.** Right now, one page that can't be processed fails the whole Map, and so the whole run, even though the other pages saved fine. I'd send `{"job_id":"x","pages":[1,0,3]}` and expect a failed run with rows for pages 1 and 3 only. Then I'd add a per-page catch that records the bad page as failed, so one broken page doesn't sink a 500-page job. That's the cloud version of D2 in Part 1.

## The shared limit of 10

The Map's limit of 3 only applies within one run. How I'd keep the whole account to 10 calls across every job and environment, and which Part 1 fixes need to work differently once each page has its own Lambda, is covered in [takeoff-pipeline/REPORT.md](../takeoff-pipeline/REPORT.md#production-the-shared-limit-and-what-changes-in-lambda).

## Not included

No `.terraform/` folder, no Terraform state, no build zips and no credentials. They're all in `.gitignore`, and the logs have the account number hidden. The provider lock file is included, so everyone gets the same provider versions.
