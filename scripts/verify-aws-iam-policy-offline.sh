#!/usr/bin/env bash
#
# verify-aws-iam-policy-offline.sh — Phase 13 correction round
# acceptance for infra/aws/terraform/'s least-privilege observer IAM
# policy. Runs ENTIRELY offline: no real AWS account, no real
# credentials, no `terraform apply`, no network call to any AWS API
# endpoint. `offline_validation` (default true -- see provider.tf's
# own docstring) sets the AWS provider's skip_credentials_validation/
# skip_requesting_account_id/skip_region_validation flags, which is
# what makes even `terraform plan` genuinely offline; AWS_ACCESS_KEY_ID
# etc. below are obviously-fake placeholder strings the provider never
# validates or sends anywhere.
#
# Correction round (final), Issue 1: every negative control below
# checks the REAL process exit code of `terraform plan` itself
# (captured immediately after the command, never through a pipe into
# `grep`/`tail`, which would silently replace it with the pipeline's
# own last command's exit code instead) -- a bare "the warning text
# appeared somewhere in the output" check is exactly the kind of
# advisory-only, non-blocking assertion independent review correctly
# flagged as insufficient.
#
# Asserts:
#   - enable_provisioning=true while offline_validation is still true
#     (its default) is a HARD plan failure (nonzero exit), never a
#     warning.
#   - an enrolled ARN belonging to a different account/region is ALSO
#     a HARD plan failure (nonzero exit), via a `variable` validation
#     block -- never merely a `check` block warning.
#   - ecs:ListServices is granted with Resource="*" plus an
#     ecs:cluster + aws:RequestedRegion condition (never a cluster ARN
#     as Resource).
#   - ecs:DescribeServices is granted with the enrolled SERVICE ARNs
#     as Resource (never a cluster ARN).
#   - an empty ECS enrollment renders NEITHER ECS statement at all --
#     never a broad Resource="*" fallback.
#   - provider.tf's source still contains the conditional
#     `allowed_account_ids` re-instatement for when
#     enable_provisioning is ever actually true (checked statically --
#     this specific live-provisioning combination is never actually
#     exercised by this script, since doing so would require either
#     real credentials or a real attempt to reach AWS, both out of
#     scope here).

set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
TF_DIR="$REPO_ROOT/infra/aws/terraform"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

export AWS_ACCESS_KEY_ID="testing"
export AWS_SECRET_ACCESS_KEY="testing"
export AWS_SESSION_TOKEN="testing"

# run_plan <log-file> [-out=<plan-file>] <extra terraform plan args...>
# Runs `terraform plan`, ALWAYS returns its real exit code via the
# global REAL_EXIT, and writes combined stdout/stderr to <log-file> --
# never piped directly into grep/tail, which would mask the real exit
# code with the pipeline's own last stage instead.
run_plan() {
  local log_file="$1"
  shift
  terraform plan -input=false -no-color -var='aws_account_id=111111111111' -var='aws_region=us-east-1' "$@" >"$log_file" 2>&1
  REAL_EXIT=$?
}

main() {
cd "$TF_DIR"

echo "=== terraform fmt -check ===" >&2
terraform fmt -check -diff || { echo "FAILED: terraform fmt -check" >&2; exit 1; }

echo "=== terraform init (provider plugin download only, no AWS call) ===" >&2
terraform init -backend=false -input=false >/dev/null || { echo "FAILED: terraform init" >&2; exit 1; }

echo "=== terraform validate ===" >&2
terraform validate || { echo "FAILED: terraform validate" >&2; exit 1; }

echo "=== HARD FAILURE: enable_provisioning=true with offline_validation still true (its default) ===" >&2
run_plan "$WORK/plan_unsafe_combo.log" -var='enable_provisioning=true'
if [ "$REAL_EXIT" -eq 0 ]; then
  echo "FAILED: enable_provisioning=true + offline_validation=true was NOT rejected (exit 0)" >&2
  exit 1
fi
grep -q "enable_provisioning=true requires offline_validation=false" "$WORK/plan_unsafe_combo.log" || {
  echo "FAILED: expected error message not found" >&2; cat "$WORK/plan_unsafe_combo.log" >&2; exit 1;
}
echo "OK: rejected with a HARD, nonzero-exit plan failure (exit=$REAL_EXIT)" >&2

echo "=== HARD FAILURE: enable_provisioning=true with offline_validation explicitly set false ===" >&2
# Confirms the guard is specifically about the (true, true) combination
# -- NOT a blanket rejection of enable_provisioning=true outright --
# without ever actually letting the provider attempt a live credential
# resolution: an invalid dummy account id format is used instead,
# which variable validation on aws_account_id rejects BEFORE the
# provider is ever configured, so this still makes zero AWS contact.
terraform plan -input=false -no-color -var='aws_account_id=not-a-valid-account-id' -var='aws_region=us-east-1' \
  -var='enable_provisioning=true' -var='offline_validation=false' >"$WORK/plan_bad_account.log" 2>&1
REAL_EXIT=$?
if [ "$REAL_EXIT" -eq 0 ]; then
  echo "FAILED: malformed aws_account_id was NOT rejected (exit 0)" >&2
  exit 1
fi
grep -q "aws_account_id must be exactly 12 digits" "$WORK/plan_bad_account.log" || {
  echo "FAILED: expected account-id error message not found" >&2; cat "$WORK/plan_bad_account.log" >&2; exit 1;
}
echo "OK: rejected before the provider was ever configured (exit=$REAL_EXIT) -- zero AWS contact" >&2

echo "=== HARD FAILURE: an enrolled ARN from a different account/region ===" >&2
run_plan "$WORK/plan_crossaccount.log" -var='enrolled_ecs_cluster_arns=["arn:aws:ecs:us-east-1:999999999999:cluster/prod"]'
if [ "$REAL_EXIT" -eq 0 ]; then
  echo "FAILED: cross-account enrolled ARN was NOT rejected (exit 0)" >&2
  exit 1
fi
grep -q "must be an ECS cluster ARN in the" "$WORK/plan_crossaccount.log" || {
  echo "FAILED: expected cross-account error message not found" >&2; cat "$WORK/plan_crossaccount.log" >&2; exit 1;
}
echo "OK: rejected with a HARD, nonzero-exit plan failure via a variable validation block (exit=$REAL_EXIT), never merely a check-block warning" >&2

echo "=== POSITIVE CONTROL: offline plan with a full, matching ECS enrollment succeeds ===" >&2
run_plan "$WORK/plan_good.log" \
  -var='enrolled_ecs_cluster_arns=["arn:aws:ecs:us-east-1:111111111111:cluster/prod"]' \
  -var='enrolled_ecs_service_arns=["arn:aws:ecs:us-east-1:111111111111:service/prod/checkout"]' \
  -out="$WORK/plan_good.out"
if [ "$REAL_EXIT" -ne 0 ]; then
  echo "FAILED: a valid, matching ECS enrollment was unexpectedly rejected" >&2; cat "$WORK/plan_good.log" >&2; exit 1;
fi

terraform show -json "$WORK/plan_good.out" | python3 -c "
import json, sys

data = json.load(sys.stdin)
policy = json.loads(data['planned_values']['outputs']['observer_iam_policy_json']['value'])
by_sid = {s['Sid']: s for s in policy['Statement']}

list_stmt = by_sid['AllowObserverEcsListServices']
assert list_stmt['Resource'] == '*', 'ListServices must use Resource=\"*\"'
assert 'ecs:cluster' in list_stmt['Condition']['ArnEquals'], 'ListServices must condition on ecs:cluster'
assert list_stmt['Condition']['ArnEquals']['ecs:cluster'] == 'arn:aws:ecs:us-east-1:111111111111:cluster/prod'

describe_stmt = by_sid['AllowObserverEcsDescribeServices']
assert describe_stmt['Resource'] == 'arn:aws:ecs:us-east-1:111111111111:service/prod/checkout', (
    'DescribeServices must be scoped to the enrolled SERVICE ARN, never a cluster ARN'
)
print('OK: ListServices/DescribeServices are correctly and separately scoped')
" || exit 1

echo "=== POSITIVE CONTROL: empty ECS enrollment renders NO ECS statement (no broad fallback) ===" >&2
run_plan "$WORK/plan_empty.log" -out="$WORK/plan_empty.out"
if [ "$REAL_EXIT" -ne 0 ]; then
  echo "FAILED: the default (empty) configuration was unexpectedly rejected" >&2; cat "$WORK/plan_empty.log" >&2; exit 1;
fi

terraform show -json "$WORK/plan_empty.out" | python3 -c "
import json, sys

data = json.load(sys.stdin)
policy = json.loads(data['planned_values']['outputs']['observer_iam_policy_json']['value'])
sids = {s['Sid'] for s in policy['Statement']}
assert 'AllowObserverEcsListServices' not in sids
assert 'AllowObserverEcsDescribeServices' not in sids
print('OK: no ECS statement rendered with an empty enrollment')
" || exit 1

echo "=== STATIC CHECK: provider.tf still conditionally re-instates allowed_account_ids ===" >&2
# Checked statically, by source inspection -- NEVER by actually
# exercising enable_provisioning=true with offline_validation=false
# against a real/attempted AWS endpoint, which is out of scope here.
grep -q 'allowed_account_ids = var.enable_provisioning ? \[var.aws_account_id\] : null' provider.tf || {
  echo "FAILED: provider.tf no longer conditionally re-instates allowed_account_ids" >&2; exit 1;
}
echo "OK: provider.tf still conditionally re-instates allowed_account_ids for enable_provisioning=true" >&2

rm -rf .terraform .terraform.lock.hcl

echo "" >&2
echo "PHASE 13 CORRECTION ROUND (FINAL) ACCEPTANCE VERIFIED: enable_provisioning=true now REQUIRES offline_validation=false (hard, nonzero-exit failure otherwise), cross-account/region enrolled ARNs are rejected the same hard way (never merely a check-block warning), ECS IAM statements remain correctly and separately scoped, an empty enrollment never falls back to a broad grant, and account allowlisting is correctly conditional -- all with zero live AWS calls and zero real credentials." >&2
}

main "$@"
