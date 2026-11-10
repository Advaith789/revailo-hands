#!/usr/bin/env bash
# End to end: fmt, validate, apply, smoke (two executions, same job id),
# destroy, verify gone. Everything is echoed and logged to
# cloud/proof/run-<UTC>.log with the 12-digit account id redacted.
#
#   cloud/prove.sh
#
# Needs AWS credentials for the target account in the environment/profile.
# The stack is destroyed even if the smoke test fails.
set -uo pipefail

cd "$(dirname "$0")"
TF="${TERRAFORM:-terraform}"
mkdir -p proof
LOG="proof/run-$(date -u +%Y%m%dT%H%M%SZ).log"
exec > >(sed -E 's/[0-9]{12}/<account-id>/g' | tee "$LOG") 2>&1

step() { echo; echo "================ $*"; }

step "context"
echo "UTC: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
"$TF" version | head -1
"${AWS_CLI:-aws}" --version
"${AWS_CLI:-aws}" sts get-caller-identity --query Arn --output text

step "terraform init"
"$TF" init -input=false -no-color | tail -3

step "terraform fmt -check -recursive"
"$TF" fmt -check -recursive && echo "fmt: OK (no changes needed)" || { echo "fmt: FAILED"; exit 1; }

step "terraform validate"
"$TF" validate -no-color || exit 1

step "terraform apply"
"$TF" apply -input=false -auto-approve -no-color | grep -vE 'Reading\.\.\.|Read complete|Still creating' || exit 1
"$TF" output -no-color

step "smoke: two executions, same job id"
./smoke.sh
smoke=$?

step "terraform destroy"
"$TF" destroy -input=false -auto-approve -no-color | grep -vE 'Reading\.\.\.|Read complete|Still destroying|Refreshing state'

step "verify destroyed"
REGION="$("$TF" output -raw region 2>/dev/null || echo us-east-2)" ./verify_destroyed.sh
gone=$?

step "result"
echo "smoke exit=$smoke  verify_destroyed exit=$gone  log=$LOG"
[ "$smoke" -eq 0 ] && [ "$gone" -eq 0 ]
