terraform {
  # Correction round (final): bumped from ">= 1.5.0" to ">= 1.9.0" --
  # variables.tf's own hard-blocking `validation` blocks now reference
  # OTHER variables (e.g. `enable_provisioning`'s own validation reads
  # `var.offline_validation`; the enrolled-ARN variables' validations
  # read `var.aws_region`/`var.aws_account_id`), a capability Terraform
  # only added in 1.9.0 ("cross-variable validation"). Terraform 1.5.0
  # DID support `check` blocks, which this module previously relied on
  # for ARN account/region consistency -- but `check` block failures
  # are WARNINGS, never a hard plan/apply failure, which is exactly the
  # gap this correction round closes by moving that enforcement into
  # `variable` validation blocks instead (see iam_policy.tf's own
  # comment on why the `check` block was removed). This module is
  # validated offline via `scripts/verify-aws-iam-policy-offline.sh`
  # against a real local Terraform binary (confirmed 1.16.x during
  # this correction round), well above this new floor.
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Deliberately NO backend block -- state is local by default, and
  # this module is never applied as part of this phase (see this
  # directory's own README). A real deployment would add an explicit,
  # reviewed remote-state backend before ever running `terraform
  # apply`, as a SEPARATE, later, human-authorized change.
}
