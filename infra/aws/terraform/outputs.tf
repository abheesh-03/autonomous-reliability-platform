output "observer_iam_policy_json" {
  description = "The rendered least-privilege observer IAM policy document (JSON) -- available even when enable_provisioning=false, for review before any real deployment."
  value       = data.aws_iam_policy_document.observer.json
}

output "observer_role_arn" {
  description = "The observer IAM role's ARN -- null while enable_provisioning=false (the default; nothing is provisioned)."
  value       = var.enable_provisioning ? aws_iam_role.observer[0].arn : null
}
