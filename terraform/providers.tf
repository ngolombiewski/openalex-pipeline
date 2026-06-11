provider "google" {
  project = var.project
  region  = var.region

  # No JSON key: impersonate the terraform-runner service account. The caller's
  # ADC identity holds roles/iam.serviceAccountTokenCreator on this SA.
  impersonate_service_account = "terraform-runner@openalex-pipeline.iam.gserviceaccount.com"
}
