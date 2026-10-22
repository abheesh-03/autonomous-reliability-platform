# AWS infrastructure preparation (Phase 13, Gate 6)

This directory is a clearly separated, **non-deploying** AWS infrastructure
preparation area. Nothing under `infra/aws/` has ever been applied against a
real AWS account as part of this phase, and nothing here provisions anything
by default.

## What's here

- `terraform/` — a parameterized Terraform module for a future least-privilege
  AWS observer IAM role. Every resource is gated behind
  `var.enable_provisioning` (default `false`); the module's `data
  "aws_iam_policy_document"` resources render JSON locally and make no AWS
  API call at all, so even running `terraform plan`/`validate` against this
  module requires no credentials and touches no real AWS account.
- `iam/observer-policy.example.json` — the same least-privilege policy, hand-
  written as plain, valid IAM JSON (placeholders `REGION`/`ACCOUNT_ID`/
  `ENROLLED_CLUSTER_NAME` only) so it can be read and reviewed without running
  Terraform at all.

## Supported AWS read APIs (exactly these, nothing else)

| API | Purpose |
| --- | --- |
| `sts:GetCallerIdentity` | Account identity verification before every observation cycle |
| `cloudwatch:DescribeAlarms` | Alarm state (ALARM/OK/INSUFFICIENT_DATA) |
| `cloudwatch:GetMetricData` | Opt-in only, disabled by default (real per-request cost) |
| `cloudtrail:LookupEvents` | Recent management events, as supporting evidence only |
| `ec2:DescribeInstances` / `ec2:DescribeInstanceStatus` | Enrolled EC2 instance state + status checks |
| `ecs:ListServices` / `ecs:DescribeServices` | Enrolled ECS cluster/service desired-vs-running counts |

No mutating action (`StartInstances`, `StopInstances`, `RebootInstances`,
`UpdateService`, `RunTask`, `PutMetricAlarm`, `CreateTrail`, `PutLogEvents`, or
any equivalent) appears anywhere in this policy, the Terraform module, or
`detectors/clients/aws_client.py`'s own `AwsClientProtocol`.

## Which permissions require broader resource scoping (and why)

AWS's own IAM authorization model does not support resource-level
permissions for every API used here:

- `cloudwatch:DescribeAlarms` / `cloudwatch:GetMetricData` — **require
  `Resource: "*"`**. CloudWatch does not support per-alarm-ARN IAM scoping for
  these two read actions. Alarm-level scope is enforced at the **application
  layer only** (`AwsObserverScope.enrolled_alarm_names` in
  `detectors/clients/aws_client.py`) — IAM itself cannot narrow this further.
- `cloudtrail:LookupEvents` — **requires `Resource: "*"`**. CloudTrail has no
  resource-level permission model for this action.
- `ec2:DescribeInstances` / `ec2:DescribeInstanceStatus` — **require
  `Resource: "*"`**. EC2's `Describe*`/`List*` read APIs do not support
  resource-level permissions at all. Instance-level scope is enforced at the
  application layer only (`AwsObserverScope.enrolled_instance_ids`).
- `ecs:ListServices` and `ecs:DescribeServices` are scoped DIFFERENTLY --
  correction round, Issue 3 fixed a bug where both actions were previously
  given the SAME cluster-ARN resource list, which real IAM evaluation would
  never actually honor for `DescribeServices`:
  - `ecs:ListServices` **requires `Resource: "*"`** -- it does not support
    resource-level ARNs at all. It is instead scoped via the `ecs:cluster`
    CONDITION key (`enrolled_ecs_cluster_arns`), which ECS DOES honor for
    this action.
  - `ecs:DescribeServices` **supports resource-level scoping via SERVICE
    ARNs** (`arn:...:service/CLUSTER/SERVICE`), never cluster ARNs. It is
    scoped via `enrolled_ecs_service_arns`.
  - Each statement is emitted ONLY when its corresponding enrollment variable
    is non-empty -- an empty enrollment omits the statement entirely rather
    than ever falling back to a broad grant.

Every statement also carries an `aws:RequestedRegion` condition, so even the
unavoidably-`Resource: "*"` statements are still confined to the one
explicitly configured region.

## Offline validation (no live AWS calls, not even `terraform plan`)

Reproduced directly during the correction round: a plain `provider "aws" {}`
block attempts real credential resolution (an EC2 IMDS probe, and -- if
`allowed_account_ids` is set -- a live STS call) at `terraform plan` time
REGARDLESS of whether any resource in the graph is actually provisioned
(every resource here is gated behind `enable_provisioning`, but that gate
does not stop the provider's own configure step).

`provider.tf` now sets `skip_credentials_validation` /
`skip_requesting_account_id` / `skip_region_validation`, all driven by
`var.offline_validation` (default `true`). With the default, `terraform
plan`/`validate` never reach a real AWS endpoint at all -- confirmed by
`scripts/verify-aws-iam-policy-offline.sh`, which runs a full plan with
placeholder `AWS_ACCESS_KEY_ID=testing` credentials and asserts the rendered
policy JSON directly.

**Correction round (final):** `offline_validation=true` no longer merely
"should" be paired with `enable_provisioning=false` -- `variables.tf`'s own
`enable_provisioning` variable now carries a HARD `validation` block that
makes `terraform plan`/`apply`/`validate` fail outright (nonzero exit) if
`enable_provisioning=true` is ever combined with `offline_validation=true`
still at its default. A human must deliberately set BOTH
`enable_provisioning = true` AND `offline_validation = false` together, as
one explicit, reviewed decision, before this module is ever pointed at a
real account -- setting only one of the two is rejected, not silently
accepted.

## Region/account restrictions

- Every enrolled ARN (`enrolled_ecs_cluster_arns`, `enrolled_ecs_service_arns`,
  `enrolled_cloudwatch_alarm_arns`) is checked against
  `var.aws_account_id`/`var.aws_region` by a HARD-BLOCKING `variable`
  `validation` block on each of those three variables (`variables.tf`) --
  purely offline, zero live calls. **Correction round (final):** this was
  previously a `check` block in `iam_policy.tf`; independent review correctly
  identified that `check` block assertion failures are WARNINGS ONLY
  (`terraform plan`/`apply` still exits 0), so the enforcement was moved to
  `variable` validation, whose failures DO stop `plan`/`apply`/`validate`
  with a nonzero exit. `scripts/verify-aws-iam-policy-offline.sh` asserts the
  real exit code directly, never just the presence of a warning string.
- Account enforcement at the PROVISIONING layer is now **conditionally
  reinstated**: `provider.tf` sets `allowed_account_ids =
  var.enable_provisioning ? [var.aws_account_id] : null`. Because
  `enable_provisioning=true` can never coexist with `offline_validation=true`
  (see above), the only time this allowlist is actually active is also the
  only time the provider is actually allowed to make the live STS call
  needed to enforce it -- never a contradiction, never silently skipped.
  While `enable_provisioning` stays at its default (`false`), this evaluates
  to `null` (equivalent to omitting it), preserving the zero-network offline
  guarantee above.
- Account enforcement at the OBSERVATION layer (separate from the
  provisioning-time check above) remains at the **application** layer, by
  `detectors/clients/aws_client.py`'s `Boto3AwsClient.verify_identity()`
  (Gate 1) -- the one place that calls STS to verify the account before any
  AWS API observation call is ever made.
- Every IAM statement conditions on `aws:RequestedRegion == var.aws_region`.
- The application-layer client (`detectors/clients/aws_client.py`) performs
  its own independent `sts:GetCallerIdentity` check and fails closed on a
  mismatch, **in addition to** (never instead of) these IAM/Terraform-level
  restrictions — defense in depth, not a single point of enforcement.

## Secure configuration (profile/role references only)

`terraform.tfvars.example` and `provider.tf` only ever reference an SDK
credential **profile name** (`var.aws_profile`) — never a literal access
key, secret key, session token, or hardcoded account id. A real
`terraform.tfvars` (if one is ever created) is excluded from version control
(see the repo's `.gitignore`: `*.tfvars` is ignored, `*.tfvars.example` is
explicitly re-allowed).

## Cost discussion

- `sts:GetCallerIdentity`, `cloudwatch:DescribeAlarms`, `cloudtrail:LookupEvents`,
  `ec2:Describe*`, and `ecs:List/DescribeServices` are all **free** API calls
  under AWS's standard pricing (no per-request charge).
- `cloudwatch:GetMetricData` is the **one** call with a real per-request cost
  (billed per metric per request). It is disabled by default in both the
  application (`Boto3AwsClient(enable_get_metric_data=False)` by default) and
  documented here as the one action an operator should budget for explicitly
  before ever opting in.
- IAM roles/policies themselves are free; this Terraform module provisions no
  billable resource at all (no EC2/ECS/RDS/CloudWatch/CloudTrail resource is
  ever created by it).
- Given the real target account is a new AWS Free-plan account with
  promotional credits and a conservative monthly cost alert (Gate 7), the
  recommended first live step is a single, manually-authorized, bounded
  smoke test with `--enable-aws-get-metric-data` left OFF.

## Future live, read-only smoke-testing — how it would work

1. A human reviews this module and `iam/observer-policy.example.json` line by
   line.
2. A human fills in a **real** `terraform.tfvars` (never committed) with the
   real account id/region, and sets `trusted_principal_arns` to the specific
   principal that will assume the role.
3. A human sets BOTH `enable_provisioning = true` AND `offline_validation =
   false` together **only after** steps 1–2 (setting only one of the two is
   rejected outright by `variables.tf`'s own hard validation -- see "Region/
   account restrictions" above), and runs `terraform plan` to review the
   exact diff before ever running `terraform apply`. Both are run by a
   human, outside of any AI-driven workflow.
4. A human runs `python -m detectors analyze --aws-observe --aws-account-id
   <id> --aws-region <region> --aws-enroll-cloudwatch-alarm <name> ...` once,
   by hand, and inspects the output before considering any further
   automation.
5. `--enable-aws-get-metric-data` stays off until a human has separately
   reviewed the expected per-run metric-query volume and cost.
6. None of the above is performed by this phase's own work — this phase only
   prepares the reviewed module and documents this checklist.

## Restrictions this directory itself upholds

- `terraform apply` has never been run.
- No `aws_iam_role`/`aws_iam_role_policy`/`aws_iam_user` (or any other AWS
  resource) has ever been created in a real account from this module.
- No real AWS account id, access key, secret key, session token, or
  profile-specific local path appears anywhere in this directory.
- `enable_provisioning` defaults to `false`, and `trusted_principal_arns`
  defaults to `[]` — even a future `terraform apply` with every other default
  left untouched would still create nothing usable (the trust policy itself
  fails to render without at least one principal).
