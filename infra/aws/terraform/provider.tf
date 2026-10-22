# Phase 13, Gate 6 / correction round Issue 3: the AWS provider is
# configured ONLY from variables/environment/profile references --
# never a hardcoded account id, access key, secret key, or session
# token anywhere in this module. `profile` is optional: when unset, the
# provider falls back to the SDK's own standard credential provider
# chain (the same discipline detectors/clients/aws_client.py's
# Boto3AwsClient already follows).
#
# `var.offline_validation` (default true -- see variables.tf) keeps
# this provider from EVER reaching a real AWS endpoint, including for
# plain `terraform plan`: reproduced directly during this correction
# round, a `provider "aws" {}` block with no `skip_*` flags attempts
# real credential resolution (including an EC2 IMDS probe and,
# depending on configuration, a live STS call) at `plan` time
# REGARDLESS of whether any resource in the graph is actually
# provisioned (every resource here is gated behind
# `enable_provisioning`, but that gate does not stop the provider's
# own configure step). Setting all three `skip_*` flags is the AWS
# provider's own documented mechanism for "never touch the network,
# ever" -- this is what makes `terraform plan`/`validate` against this
# module genuinely offline, consistent with this phase's "no live AWS
# calls" restriction. A human must deliberately set
# `offline_validation = false`, as a separate, reviewed decision (at
# the same time as `enable_provisioning`), before this module is ever
# pointed at a real AWS account.
#
# Correction round (final), Issue 1: `allowed_account_ids` is
# REINSTATED here -- conditionally. `variables.tf`'s own hard
# validation block guarantees `var.enable_provisioning=true` can NEVER
# coexist with `var.offline_validation=true`, so the moment real
# provisioning is ever actually enabled, `offline_validation` is
# necessarily false, `skip_requesting_account_id` is necessarily
# false, and the provider genuinely CAN (and must) request the live
# account id to enforce this allowlist -- live account verification is
# the explicit, intended behavior for that one, deliberately-chosen
# combination, never an accident. While `enable_provisioning` stays at
# its default (false), `allowed_account_ids` evaluates to `null`
# (equivalent to omitting it entirely), and the three `skip_*` flags
# below (still driven by `offline_validation`, default true) keep this
# provider from ever reaching a real AWS endpoint -- confirmed offline
# via `scripts/verify-aws-iam-policy-offline.sh`.
#
# Defense in depth, not the only enforcement: Gate 1's own application-
# layer check, detectors/clients/aws_client.py's
# Boto3AwsClient.verify_identity(), remains the one place in this whole
# platform that actually calls STS during real AWS OBSERVATION (as
# opposed to Terraform's own, separate account check at PROVISIONING
# time, which is what this provider block's `allowed_account_ids`
# guards).
provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile

  allowed_account_ids = var.enable_provisioning ? [var.aws_account_id] : null

  skip_credentials_validation = var.offline_validation
  skip_requesting_account_id  = var.offline_validation
  skip_region_validation      = var.offline_validation

  default_tags {
    tags = {
      ManagedBy = "terraform"
      Project   = "autonomous-reliability-platform"
      Purpose   = "aws-observer-least-privilege"
    }
  }
}
