# Part 2 Cloud Proof

## 1. Region and time

- **Region:** `us-east-2`
- **Time:** 2026-11-10, 18:06:24 UTC
- **Account ID:** Hidden as `<account-id>`.

## How to run it

```bash
cd cloud
./prove.sh     # init, fmt-check, validate, apply, smoke test, destroy, final check
```

Or step by step: `terraform apply`, then `./smoke.sh`, then `terraform destroy`, then `./verify_destroyed.sh`. To test the worker on its own: `cd cloud/lambda && python -m pytest` (8 passed).

## 2. fmt, validate, apply, and SUCCEEDED

```
$ terraform fmt -check -recursive
fmt: OK (no changes needed)

$ terraform validate
Success! The configuration is valid.

$ terraform apply -auto-approve
Apply complete! Resources: 9 added, 0 changed, 0 destroyed.
state_machine_arn = "arn:aws:states:us-east-2:<account-id>:stateMachine:revailo-takeoff-demo-pages"
table_name = "revailo-takeoff-demo-results"

$ aws stepfunctions start-execution --state-machine-arn "$SM_ARN" \
    --name smoke-20261110T180703Z-run1-180703 \
    --input '{"job_id":"smoke-20261110T180703Z","pages":[1,2,3]}'
$ aws stepfunctions describe-execution --execution-arn "$EXEC_ARN" --query status
SUCCEEDED
```

## 3. Table rows after the first run and after the replay

Query by job ID:

```
$ aws dynamodb query --table-name revailo-takeoff-demo-results \
    --key-condition-expression 'job_id = :j' \
    --expression-attribute-values '{":j":{"S":"smoke-20261110T180703Z"}}'
```

After the first run:

```
|  smoke-20261110T180703Z |  1 |  10 |  smoke-20261110T180703Z-run1-180703  |
|  smoke-20261110T180703Z |  2 |  20 |  smoke-20261110T180703Z-run1-180703  |
|  smoke-20261110T180703Z |  3 |  30 |  smoke-20261110T180703Z-run1-180703  |
```

The replay used a new execution name (`smoke-20261110T180703Z-replay-180711`) and the same job ID. It also reached `SUCCEEDED`. The table is unchanged:

```
|  smoke-20261110T180703Z |  1 |  10 |  smoke-20261110T180703Z-run1-180703  |
|  smoke-20261110T180703Z |  2 |  20 |  smoke-20261110T180703Z-run1-180703  |
|  smoke-20261110T180703Z |  3 |  30 |  smoke-20261110T180703Z-run1-180703  |
```

There are still exactly 3 rows with areas 10, 20 and 30. The last column still shows the first run as the writer, so the replay did not overwrite anything. The worker saves a row only if it does not already exist. If the row exists, the worker skips the write and still succeeds.

## 4. Destroy and final check

```
$ terraform destroy -auto-approve
Destroy complete! Resources: 9 destroyed.

$ ./verify_destroyed.sh
terraform state list: (empty)
gone: DynamoDB table -> ResourceNotFoundException
gone: Lambda -> ResourceNotFoundException
gone: State machine -> StateMachineDoesNotExist
gone: IAM roles (2) -> NoSuchEntity
gone: Log group -> (no match)
```

## 5. What I could not verify, and the next failure mode to test

**What I could not verify:**
- A retry of one page inside the same run.
- Two runs for the same job starting at the exact same moment.

**The next failure mode to test:** One bad page. Right now, one page that fails stops the whole run, even though the other pages are saved. I would send `{"job_id":"x","pages":[1,0,3]}` and then add a per-page catch, so that one broken page does not fail a 500-page job.

## Extras

- **A real failure, caught and fixed:** The first run failed with "access denied" because AWS had not finished applying the new permissions. I added a 15-second wait before the state machine is created. Both logs are in [proof/](proof/).
- **Tight permissions:** Each IAM role is limited to the one resource it needs.
- **One-command proof:** `prove.sh` saves a full log with the account ID hidden.
