# Phase 13, Gate 6: every resource below is gated behind
# `count = var.enable_provisioning ? 1 : 0` -- with the module's own
# default (enable_provisioning=false), `terraform plan`/`terraform
# apply` creates NOTHING. This phase never sets enable_provisioning to
# true and never runs `terraform apply` at all (see this directory's
# README). `trusted_principal_arns` also defaults to empty, so even a
# future `enable_provisioning=true` run with no further changes would
# produce a role nothing could ever actually assume -- fail closed in
# two independent, deliberately redundant ways.
data "aws_iam_policy_document" "observer_trust" {
  count = var.enable_provisioning ? 1 : 0

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    dynamic "principals" {
      for_each = length(var.trusted_principal_arns) > 0 ? [1] : []
      content {
        type        = "AWS"
        identifiers = var.trusted_principal_arns
      }
    }

    # No `principals` block at all when trusted_principal_arns is
    # empty -- the rendered trust policy then has no `Principal` at
    # all, which AWS's own IAM API rejects as an invalid
    # AssumeRolePolicyDocument at apply time (never silently "trust
    # everyone"). This is a deliberate second, redundant fail-closed
    # layer on top of enable_provisioning itself defaulting to false.
  }
}

resource "aws_iam_role" "observer" {
  count = var.enable_provisioning ? 1 : 0

  name               = var.observer_role_name
  assume_role_policy = data.aws_iam_policy_document.observer_trust[0].json
  description        = "Phase 13 least-privilege AWS observer role -- read-only CloudWatch/CloudTrail/EC2/ECS/STS access only."

  # Correction round (final), Issue 1: a THIRD, redundant, resource-
  # level hard guard on top of (1) variables.tf's own
  # enable_provisioning/offline_validation cross-validation and (2)
  # provider.tf's conditional allowed_account_ids -- this precondition
  # is evaluated at plan/apply time for this SPECIFIC resource (which
  # only exists at all when count=1, i.e. enable_provisioning=true) and
  # fails the whole plan/apply hard if offline_validation is somehow
  # still true then. Deliberately redundant: this resource could only
  # ever be reached with enable_provisioning=true, and the variable
  # validation above already guarantees offline_validation=false in
  # that case -- this precondition exists purely as defense in depth
  # against a future refactor accidentally removing or weakening that
  # variable-level guard.
  lifecycle {
    precondition {
      condition     = !var.offline_validation
      error_message = "enable_provisioning=true must never be combined with offline_validation=true -- this resource would otherwise be provisioned through a provider still configured to skip AWS credential/account verification."
    }
  }
}

resource "aws_iam_role_policy" "observer" {
  count = var.enable_provisioning ? 1 : 0

  name   = "${var.observer_role_name}-read-only"
  role   = aws_iam_role.observer[0].id
  policy = data.aws_iam_policy_document.observer.json
}
