#!/usr/bin/env bash
# After `terraform destroy`: show that Terraform state is empty and that each
# resource the stack created is gone from AWS. Exits non-zero if any remains.
set -uo pipefail

cd "$(dirname "$0")"
TF="${TERRAFORM:-terraform}"
AWS="${AWS_CLI:-aws}"
NAME="${NAME:-revailo-takeoff-demo}"
REGION="${REGION:-us-east-2}"
left=0

gone() {  # gone <description> <command...>: command must fail with a not-found error
  local what="$1"; shift
  local out
  if out="$("$@" 2>&1)"; then
    echo "STILL EXISTS: $what"; left=1
  else
    echo "gone: $what -> $(echo "$out" | grep -oE '[A-Za-z]+(NotFound|DoesNotExist|NoSuchEntity)[A-Za-z]*' | head -1)"
  fi
}

echo "\$ terraform state list"
state="$("$TF" state list 2>/dev/null)"
if [ -n "$state" ]; then echo "$state"; left=1; else echo "(empty)"; fi

ACCOUNT="$("$AWS" sts get-caller-identity --query Account --output text)"
gone "DynamoDB table $NAME-results" \
  "$AWS" dynamodb describe-table --region "$REGION" --table-name "$NAME-results"
gone "Lambda $NAME-worker" \
  "$AWS" lambda get-function --region "$REGION" --function-name "$NAME-worker"
gone "State machine $NAME-pages" \
  "$AWS" stepfunctions describe-state-machine --region "$REGION" \
  --state-machine-arn "arn:aws:states:$REGION:$ACCOUNT:stateMachine:$NAME-pages"
gone "IAM role $NAME-worker" "$AWS" iam get-role --role-name "$NAME-worker"
gone "IAM role $NAME-sfn" "$AWS" iam get-role --role-name "$NAME-sfn"

lg="$("$AWS" logs describe-log-groups --region "$REGION" \
  --log-group-name-prefix "/aws/lambda/$NAME-worker" --query 'logGroups[].logGroupName' --output text)"
if [ -n "$lg" ]; then echo "STILL EXISTS: log group $lg"; left=1; else echo "gone: log group /aws/lambda/$NAME-worker -> (no match)"; fi

exit "$left"
