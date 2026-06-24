variable "project" {
  description = "GCP project ID."
  type        = string
  default     = "openalex-pipeline"
}

variable "region" {
  description = "Default GCP region for regional resources. BigQuery datasets do not use this; they must live in the EU multi-region to match the bucket (see bigquery.tf)."
  type        = string
  default     = "europe-west3"
}

variable "dbt_impersonator" {
  description = "IAM principal allowed to impersonate the dbt service account (token creator), e.g. \"user:you@example.com\". The developer's ADC identity that runs dbt locally. Set in terraform.tfvars (gitignored); no default so a missing value fails loudly rather than granting the wrong identity."
  type        = string
  sensitive   = true
}
