output "bronze_bucket" {
  value = google_storage_bucket.bronze.name
}

output "raw_dataset" {
  value = google_bigquery_dataset.raw.dataset_id
}

output "analytics_dataset" {
  value = google_bigquery_dataset.analytics.dataset_id
}

output "analytics_dev_dataset" {
  value = google_bigquery_dataset.analytics_dev.dataset_id
}

output "bronze_external_table" {
  value = "${google_bigquery_dataset.raw.dataset_id}.${google_bigquery_table.bronze_external.table_id}"
}

output "dbt_service_account" {
  value = google_service_account.dbt.email
}
