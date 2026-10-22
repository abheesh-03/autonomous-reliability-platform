variable "trusted_principal_arns" {
  description = <<-EOT
    Explicit IAM principal ARNs (users/roles) allowed to assume the
    observer role, if/when it is ever provisioned. Defaults to empty,
    which means the generated trust policy trusts NOTHING and the role
    (if provisioned) could never actually be assumed by anyone --
    deliberately fail-closed rather than defaulting to "anyone in this
    account". A human operator must set this explicitly, as part of
    the same reviewed decision that sets enable_provisioning=true.
  EOT
  type        = list(string)
  default     = []
}
