terraform {
  required_version = ">= 1.9"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # Local backend for now: state lives in this directory (gitignored).
  # migrate to GCS after first apply.
  backend "local" {}
}

variable "project" {
  description = "GCP project ID."
  type        = string
  default     = "openalex-pipeline"
}

variable "region" {
  description = "Default GCP region for regional resources."
  type        = string
  default     = "europe-west3" # Okay for now, revisit for BigQuery (EU)
}

provider "google" {
  project = var.project
  region  = var.region

  # No JSON key: impersonate the terraform-runner service account. The caller's
  # ADC identity holds roles/iam.serviceAccountTokenCreator on this SA.
  impersonate_service_account = "terraform-runner@openalex-pipeline.iam.gserviceaccount.com"
}
