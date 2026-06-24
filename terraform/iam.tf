# Identity for dbt's BigQuery work. A dedicated service account, impersonated
# the same way Terraform impersonates terraform-runner (providers.tf): the
# caller's ADC holds tokenCreator on it, no JSON key.
# Least privilege: run query jobs (project), write the analytics datasets,
# read the raw external table, and read the bronze Parquet in GCS — the last
# is required because external-table queries read GCS as the querying identity.

resource "google_service_account" "dbt" {
  account_id   = "dbt-runner"
  display_name = "dbt BigQuery runner"
  description  = "Identity dbt impersonates to build the analytics datasets."
}

# Run query jobs. Project-scoped: jobUser is not a dataset-level role.
resource "google_project_iam_member" "dbt_job_user" {
  project = var.project
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.dbt.email}"
}

# Create/replace native tables in the two analytics datasets.
resource "google_bigquery_dataset_iam_member" "dbt_analytics_editor" {
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.dbt.email}"
}

resource "google_bigquery_dataset_iam_member" "dbt_analytics_dev_editor" {
  dataset_id = google_bigquery_dataset.analytics_dev.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.dbt.email}"
}

# Read the bronze external table.
resource "google_bigquery_dataset_iam_member" "dbt_raw_viewer" {
  dataset_id = google_bigquery_dataset.raw.dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.dbt.email}"
}

# Read the bronze Parquet behind the external table. Most fragile grant: an
# external-table query reads GCS as the querying identity, so without this the
# table resolves but every scan fails with an access error.
resource "google_storage_bucket_iam_member" "dbt_bronze_object_viewer" {
  bucket = google_storage_bucket.bronze.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.dbt.email}"
}

# Let the developer's ADC impersonate the dbt SA (mirrors the terraform-runner
# pattern). Additive per-principal grant, not a full policy.
resource "google_service_account_iam_member" "dbt_impersonation" {
  service_account_id = google_service_account.dbt.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = var.dbt_impersonator
}
