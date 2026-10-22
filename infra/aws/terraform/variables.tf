variable "aws_account_id" {
  description = "The one explicit 12-digit AWS account id this module is ever allowed to target. No default -- a caller must set this explicitly."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must be exactly 12 digits."
  }
}

variable "aws_region" {
  description = "The one explicit AWS region this module is ever allowed to target. No default -- a caller must set this explicitly."
  type        = string

  validation {
    condition     = can(regex("^[a-z]{2}(-gov|-iso[a-z]*)?-[a-z]+-[0-9]$", var.aws_region))
    error_message = "aws_region must be a well-formed AWS region identifier (e.g. us-east-1)."
  }
}

variable "aws_profile" {
  description = "Optional named SDK credential profile. Never a literal access key/secret -- leave unset to use the default credential provider chain."
  type        = string
  default     = null
}

variable "offline_validation" {
  description = <<-EOT
    Defaults to true: the AWS provider is configured with
    skip_credentials_validation/skip_requesting_account_id/
    skip_region_validation all set to true, so Terraform never reaches
    a real AWS endpoint -- not even for `terraform plan` (see
    provider.tf's own docstring for why this is necessary, not merely
    cautious). A human must deliberately set this to false, as a
    separate, reviewed decision made at the same time as
    enable_provisioning, before this module is ever pointed at a real
    AWS account.
  EOT
  type        = bool
  default     = true
}

variable "enable_provisioning" {
  description = <<-EOT
    Master off switch for every resource in this module. Defaults to
    false, which means `terraform plan`/`terraform apply` against the
    DEFAULT variable values creates NOTHING -- every resource below is
    gated behind `count = var.enable_provisioning ? 1 : 0`. A human
    operator must deliberately set this to true, as a separate,
    reviewed decision, before anything here is ever provisioned (see
    this directory's README "Future provisioning checklist").
  EOT
  type        = bool
  default     = false

  # Correction round (final), Issue 1: a HARD, plan/apply-blocking
  # failure (never merely a `check` block warning) if a caller ever
  # sets enable_provisioning=true while offline_validation is STILL
  # true -- that combination would "provision" real resources through
  # a provider explicitly configured to skip all credential/account-id
  # verification (see provider.tf), which is never a safe combination.
  # Requires Terraform >= 1.9.0 for cross-variable validation (see
  # versions.tf).
  validation {
    condition     = !var.enable_provisioning || !var.offline_validation
    error_message = "enable_provisioning=true requires offline_validation=false (set as a separate, deliberate decision) -- real provisioning must never run through a provider still configured to skip AWS credential/account verification."
  }
}

variable "enrolled_ec2_instance_ids" {
  description = "Explicit EC2 instance ids this policy's EC2 read permissions are scoped to (documentation/condition purposes -- DescribeInstances/DescribeInstanceStatus themselves require Resource=\"*\" at the IAM level; see README)."
  type        = list(string)
  default     = []
}

variable "enrolled_ecs_cluster_arns" {
  description = <<-EOT
    Explicit ECS cluster ARNs used ONLY as the `ecs:cluster` CONDITION
    key value on the ecs:ListServices statement -- correction round,
    Issue 3: ListServices does not support resource-level ARNs at all
    (AWS requires Resource="*" for it); this variable scopes it via the
    condition key instead, never as a Resource value. See
    `enrolled_ecs_service_arns` for the separate variable that DOES
    scope ecs:DescribeServices's own Resource list.
  EOT
  type        = list(string)
  default     = []

  # Correction round (final), Issue 1: a HARD, plan/apply-blocking
  # failure (moved here from iam_policy.tf's own now-removed `check`
  # block, whose assertion failures were only ever WARNINGS) if any
  # enrolled cluster ARN belongs to a different account/region than
  # this module is explicitly configured for.
  validation {
    condition = alltrue([
      for arn in var.enrolled_ecs_cluster_arns :
      can(regex(":ecs:${var.aws_region}:${var.aws_account_id}:cluster/", arn))
    ])
    error_message = "every enrolled_ecs_cluster_arns entry must be an ECS cluster ARN in the configured aws_region/aws_account_id."
  }
}

variable "enrolled_ecs_service_arns" {
  description = <<-EOT
    Explicit ECS service ARNs (format
    arn:aws:ecs:REGION:ACCOUNT_ID:service/CLUSTER_NAME/SERVICE_NAME)
    that ecs:DescribeServices's own Resource list is scoped to --
    correction round, Issue 3: DescribeServices supports resource-level
    scoping via service ARNs, NOT cluster ARNs. Left empty (the
    default), the DescribeServices statement is omitted entirely from
    the rendered policy -- never a broad Resource="*" fallback.
  EOT
  type        = list(string)
  default     = []

  validation {
    condition = alltrue([
      for arn in var.enrolled_ecs_service_arns :
      can(regex(":ecs:${var.aws_region}:${var.aws_account_id}:service/", arn))
    ])
    error_message = "every enrolled_ecs_service_arns entry must be an ECS service ARN in the configured aws_region/aws_account_id."
  }
}

variable "enrolled_cloudwatch_alarm_arns" {
  description = "Explicit CloudWatch alarm ARNs this policy's CloudWatch read permissions are scoped to (DescribeAlarms itself requires Resource=\"*\"; see README)."
  type        = list(string)
  default     = []

  validation {
    condition = alltrue([
      for arn in var.enrolled_cloudwatch_alarm_arns :
      can(regex(":cloudwatch:${var.aws_region}:${var.aws_account_id}:alarm:", arn))
    ])
    error_message = "every enrolled_cloudwatch_alarm_arns entry must be a CloudWatch alarm ARN in the configured aws_region/aws_account_id."
  }
}

variable "observer_role_name" {
  description = "The name to give the (not-yet-provisioned) least-privilege IAM role, if/when enable_provisioning is ever set to true."
  type        = string
  default     = "reliability-platform-aws-observer"
}
