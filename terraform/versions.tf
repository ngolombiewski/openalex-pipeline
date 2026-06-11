terraform {
  required_version = ">= 1.9"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # State lives in the bronze bucket itself. The bucket was bootstrapped with
  # a local backend, then state was migrated here after the first apply.
  backend "gcs" {
    bucket = "openalex-pipeline-bronze"
    prefix = "terraform/state"
  }
}
