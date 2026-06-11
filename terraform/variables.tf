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
