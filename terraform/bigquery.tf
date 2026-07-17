# BigQuery surface: three datasets + the bronze external table.
# Design: docs/design-archive/staging-design.md §1–§2.

# Dataset locations must match the bucket's EU multi-region, or external
# queries fail. Independent of var.region (europe-west3), which BigQuery
# would reject here.
locals {
  bq_location = "EU"
}

resource "google_bigquery_dataset" "raw" {
  dataset_id  = "openalex_raw"
  location    = local.bq_location
  description = "GCS-handoff namespace: holds only the bronze external table."

  # Loud-guard default: terraform destroy deletes the managed external table,
  # then succeeds only if the dataset is empty. Anything unexpected in here
  # fails the destroy instead of being silently deleted.
  delete_contents_on_destroy = false
}

resource "google_bigquery_dataset" "analytics" {
  dataset_id  = "openalex_analytics"
  location    = local.bq_location
  description = "dbt prod target: staging/silver/gold native tables."

  # Contents are dbt-rebuildable from the external table with one dbt run.
  delete_contents_on_destroy = true

  # Compressed (physical) storage billing: BigQuery compresses the parsed
  # native tables ~11.5x (measured on stg_works: 22.9 GiB logical -> 2.0 GiB
  # physical), so physical billing keeps the analytics datasets under the 10 GiB
  # free tier despite its 2x per-GiB rate. Trade-off: physical also bills
  # time-travel + fail-safe bytes, and dbt's CREATE OR REPLACE leaves an old
  # version behind on every rebuild — so cap time travel at the 48h minimum to
  # bound rebuild churn (fail-safe is a fixed, non-configurable 7 days).
  # Note: the billing model can only be changed once per 14 days per dataset.
  storage_billing_model = "PHYSICAL"
  max_time_travel_hours = 48
}

resource "google_bigquery_dataset" "analytics_dev" {
  dataset_id  = "openalex_analytics_dev"
  location    = local.bq_location
  description = "dbt dev target: same models over a year slice."

  delete_contents_on_destroy = true

  # Physical storage billing — see openalex_analytics above. Especially apt here:
  # dev churns through full rebuilds on the decade slice, and the 48h time-travel
  # cap keeps that churn from accumulating physical bytes.
  storage_billing_model = "PHYSICAL"
  max_time_travel_hours = 48
}

# External table over the Hive-partitioned bronze Parquet in GCS.
# Schema is pinned (DATA_MODEL.md "Included columns"), not autodetected.
# The eight nested fields are raw JSON strings in bronze, hence STRING here.
# publication_year is supplied by the Hive partition key and must NOT be in
# the declared schema — BigQuery rejects creation when a field is in both the
# schema and the partition key. The API nevertheless *returns* the schema with
# the partition column appended, so without ignore_changes Terraform would see
# a permanent diff and force-replace the table on every plan. Hence the
# lifecycle block — with one consequence to know: ignore_changes also ignores
# edits to the schema below, so a deliberate schema change produces NO plan
# diff. To apply one, recreate the table explicitly:
#   terraform apply -replace=google_bigquery_table.bronze_external
resource "google_bigquery_table" "bronze_external" {
  dataset_id = google_bigquery_dataset.raw.dataset_id
  table_id   = "bronze_external"

  # The table definition is a pointer; recreating it is free.
  deletion_protection = false

  external_data_configuration {
    source_format = "PARQUET"
    autodetect    = false
    source_uris   = ["gs://${google_storage_bucket.bronze.name}/bronze/*"]

    hive_partitioning_options {
      mode                     = "CUSTOM"
      source_uri_prefix        = "gs://${google_storage_bucket.bronze.name}/bronze/{publication_year:INTEGER}"
      require_partition_filter = false
    }
  }

  schema = jsonencode([
    { name = "id", type = "STRING", mode = "NULLABLE" },
    { name = "title", type = "STRING", mode = "NULLABLE" },
    { name = "publication_date", type = "STRING", mode = "NULLABLE" },
    { name = "type", type = "STRING", mode = "NULLABLE" },
    { name = "language", type = "STRING", mode = "NULLABLE" },
    { name = "is_retracted", type = "BOOLEAN", mode = "NULLABLE" },
    { name = "is_paratext", type = "BOOLEAN", mode = "NULLABLE" },
    { name = "primary_topic", type = "STRING", mode = "NULLABLE" },
    { name = "topics", type = "STRING", mode = "NULLABLE" },
    { name = "cited_by_count", type = "INTEGER", mode = "NULLABLE" },
    { name = "counts_by_year", type = "STRING", mode = "NULLABLE" },
    { name = "cited_by_percentile_year", type = "STRING", mode = "NULLABLE" },
    { name = "citation_normalized_percentile", type = "STRING", mode = "NULLABLE" },
    { name = "fwci", type = "FLOAT", mode = "NULLABLE" },
    { name = "referenced_works_count", type = "INTEGER", mode = "NULLABLE" },
    { name = "open_access", type = "STRING", mode = "NULLABLE" },
    { name = "doi", type = "STRING", mode = "NULLABLE" },
    { name = "ids", type = "STRING", mode = "NULLABLE" },
    { name = "keywords", type = "STRING", mode = "NULLABLE" },
    { name = "updated_date", type = "STRING", mode = "NULLABLE" },
  ])

  lifecycle {
    ignore_changes = [schema]
  }
}
