#!/usr/bin/env bash
# Smoke test: run the workflow twice for the same job id (two different
# execution names) and check the table holds exactly pages 1,2,3 with areas
# 10,20,30 after each run. Reads the state machine ARN and table name from
# Terraform outputs. Exits non-zero on any mismatch.
#
#   cloud/smoke.sh                 # job id defaults to smoke-<UTC timestamp>
#   JOB_ID=my-job cloud/smoke.sh
set -euo pipefail

cd "$(dirname "$0")"
TF="${TERRAFORM:-terraform}"
AWS="${AWS_CLI:-aws}"

SM_ARN="$("$TF" output -raw state_machine_arn)"
TABLE="$("$TF" output -raw table_name)"
REGION="$("$TF" output -raw region)"
JOB_ID="${JOB_ID:-smoke-$(date -u +%Y%m%dT%H%M%SZ)}"
INPUT="{\"job_id\":\"$JOB_ID\",\"pages\":[1,2,3]}"
EXPECTED=$'1\t10\n2\t20\n3\t30'

echo "region=$REGION table=$TABLE job_id=$JOB_ID"

run_execution() {
  local name="$1" arn status
  echo
  echo "\$ aws stepfunctions start-execution --name $name --input '$INPUT'"
  arn="$("$AWS" stepfunctions start-execution --region "$REGION" \
    --state-machine-arn "$SM_ARN" --name "$name" --input "$INPUT" \
    --query executionArn --output text)"
  for _ in $(seq 1 60); do
    status="$("$AWS" stepfunctions describe-execution --region "$REGION" \
      --execution-arn "$arn" --query status --output text)"
    [ "$status" != "RUNNING" ] && break
    sleep 2
  done
  echo "\$ aws stepfunctions describe-execution --execution-arn <arn> --query '[name,status,startDate,stopDate]'"
  "$AWS" stepfunctions describe-execution --region "$REGION" --execution-arn "$arn" \
    --query '[name,status,startDate,stopDate]' --output text
  if [ "$status" != "SUCCEEDED" ]; then
    echo "execution $name ended $status" >&2
    "$AWS" stepfunctions describe-execution --region "$REGION" --execution-arn "$arn" \
      --query '[error,cause]' --output text >&2
    exit 1
  fi
  echo "\$ aws stepfunctions describe-execution --execution-arn <arn> --query output"
  "$AWS" stepfunctions describe-execution --region "$REGION" --execution-arn "$arn" \
    --query output --output text
}

check_rows() {
  local label="$1" rows
  echo
  echo "\$ aws dynamodb query --table-name $TABLE --consistent-read \\"
  echo "    --key-condition-expression 'job_id = :j' --expression-attribute-values '{\":j\":{\"S\":\"$JOB_ID\"}}'"
  "$AWS" dynamodb query --region "$REGION" --table-name "$TABLE" --consistent-read \
    --key-condition-expression "job_id = :j" \
    --expression-attribute-values "{\":j\":{\"S\":\"$JOB_ID\"}}" \
    --query 'Items[].[job_id.S,page_no.N,area_sqft.N,first_execution.S]' --output table
  rows="$("$AWS" dynamodb query --region "$REGION" --table-name "$TABLE" --consistent-read \
    --key-condition-expression "job_id = :j" \
    --expression-attribute-values "{\":j\":{\"S\":\"$JOB_ID\"}}" \
    --query 'Items[].[page_no.N,area_sqft.N]' --output text)"
  if [ "$rows" != "$EXPECTED" ]; then
    echo "FAIL ($label): expected exactly pages 1,2,3 with 10,20,30; got:" >&2
    echo "$rows" >&2
    exit 1
  fi
  echo "OK ($label): exactly 3 rows, areas 10/20/30"
}

run_execution "$JOB_ID-run1-$(date -u +%H%M%S)"
check_rows "after first execution"

run_execution "$JOB_ID-replay-$(date -u +%H%M%S)"
check_rows "after replay with same job id, new execution name"
