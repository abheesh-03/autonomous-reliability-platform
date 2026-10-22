# Phase 13, Gate 6: the reviewed, least-privilege AWS observer IAM
# policy -- expressed as a `aws_iam_policy_document` DATA source. This
# is a pure, LOCAL HCL evaluation: it renders a JSON policy document
# in memory and makes NO AWS API call at all (unlike, e.g.,
# `aws_caller_identity`/`aws_region` data sources) -- `terraform plan`
# against this file alone never reaches AWS, and `terraform validate`
# needs no credentials whatsoever.
#
# Every action here is READ-ONLY -- this document grants exactly the 7
# read APIs detectors/clients/aws_client.py's AwsClientProtocol
# exposes (STS GetCallerIdentity; CloudWatch DescribeAlarms/
# GetMetricData; CloudTrail LookupEvents; EC2 DescribeInstances/
# DescribeInstanceStatus; ECS ListServices/DescribeServices) and
# nothing else -- no Start*/Stop*/Reboot*/Terminate*/Update*/Run*/
# Put*/Create*/Delete* action appears anywhere in this file.
data "aws_iam_policy_document" "observer" {
  # STS: required so the observer can verify its own live account
  # identity before ever collecting anything (Gate 1: "fail closed on
  # account/Region mismatch"). GetCallerIdentity has no resource-level
  # permission support at all -- Resource="*" is the ONLY valid form
  # AWS accepts for this action, not a scoping choice made here.
  statement {
    sid       = "AllowObserverIdentityVerification"
    effect    = "Allow"
    actions   = ["sts:GetCallerIdentity"]
    resources = ["*"]
  }

  # CloudWatch: alarm state is the one read this policy scopes with an
  # explicit region condition. DescribeAlarms/GetMetricData do NOT
  # support resource-level (per-alarm-ARN) permissions in IAM --
  # AWS requires Resource="*" for both; this is a documented AWS API
  # limitation, not a gap in this policy's own design (see this
  # directory's README "Broader resource scoping" section).
  statement {
    sid       = "AllowObserverCloudWatchRead"
    effect    = "Allow"
    actions   = ["cloudwatch:DescribeAlarms", "cloudwatch:GetMetricData"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }
  }

  # CloudTrail: LookupEvents also requires Resource="*" (no
  # resource-level permission support) -- the SAME documented AWS
  # limitation as CloudWatch above.
  statement {
    sid       = "AllowObserverCloudTrailRead"
    effect    = "Allow"
    actions   = ["cloudtrail:LookupEvents"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }
  }

  # EC2: DescribeInstances/DescribeInstanceStatus ALSO require
  # Resource="*" -- EC2's Describe*/List* read APIs do not support
  # resource-level permissions in IAM at all (this is independent of
  # how this account's own `AwsObserverScope.enrolled_instance_ids`
  # bounds the actual request parameters at the application layer --
  # that enrollment is enforced in detectors/clients/aws_client.py,
  # never by IAM, because IAM has no mechanism to enforce it here).
  statement {
    sid       = "AllowObserverEc2Read"
    effect    = "Allow"
    actions   = ["ec2:DescribeInstances", "ec2:DescribeInstanceStatus"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }
  }

  # Correction round, Issue 3: ListServices and DescribeServices are
  # NOT scoped the same way -- they were previously (incorrectly)
  # given the SAME cluster-ARN resource list, which is invalid for
  # DescribeServices (it does not accept cluster ARNs as Resource) and
  # unnecessary for ListServices (which requires Resource="*" outright
  # and is scoped via the `ecs:cluster` CONDITION key instead). Each
  # is now its own statement, with its own correct scoping mechanism,
  # and -- "avoid broad fallback grants when no clusters/services are
  # enrolled" -- each statement is emitted ONLY when the corresponding
  # enrollment variable is non-empty; an empty enrollment omits the
  # statement entirely rather than ever falling back to Resource="*"
  # or an unconditioned ecs:cluster match.
  dynamic "statement" {
    for_each = length(var.enrolled_ecs_cluster_arns) > 0 ? [1] : []
    content {
      sid    = "AllowObserverEcsListServices"
      effect = "Allow"
      # ecs:ListServices does NOT support resource-level ARNs at all
      # -- AWS requires Resource="*" for this action; scoped instead
      # via the `ecs:cluster` condition key below, which ECS DOES
      # honor for this action.
      actions   = ["ecs:ListServices"]
      resources = ["*"]

      condition {
        test     = "StringEquals"
        variable = "aws:RequestedRegion"
        values   = [var.aws_region]
      }
      condition {
        test     = "ArnEquals"
        variable = "ecs:cluster"
        values   = var.enrolled_ecs_cluster_arns
      }
    }
  }

  dynamic "statement" {
    for_each = length(var.enrolled_ecs_service_arns) > 0 ? [1] : []
    content {
      sid    = "AllowObserverEcsDescribeServices"
      effect = "Allow"
      # ecs:DescribeServices DOES support resource-level scoping, via
      # SERVICE ARNs specifically -- never cluster ARNs (the bug this
      # correction round fixes: the same cluster-ARN list was
      # previously reused here, which real ECS IAM evaluation would
      # never actually match against a service-level request).
      actions   = ["ecs:DescribeServices"]
      resources = var.enrolled_ecs_service_arns

      condition {
        test     = "StringEquals"
        variable = "aws:RequestedRegion"
        values   = [var.aws_region]
      }
    }
  }
}

# Correction round (final), Issue 1: "Validate ARN account/Region
# consistency" is now ENFORCED, not merely advised -- the `check`
# block previously here has been REMOVED and replaced with hard-
# blocking `validation` blocks directly on `enrolled_ecs_cluster_arns`/
# `enrolled_ecs_service_arns`/`enrolled_cloudwatch_alarm_arns` in
# variables.tf. The reason: Terraform `check` block assertion failures
# are WARNINGS ONLY -- `terraform plan`/`apply` still exits 0 even when
# one fails, which independent review correctly identified as
# "advisory only", never an actual guard. A `variable` `validation`
# block failure, by contrast, is a hard error that stops `plan`/
# `apply`/`validate` outright (nonzero exit) -- see
# scripts/verify-aws-iam-policy-offline.sh's own negative controls.
