# GCS Upload Asset — Design

*Status: Designed, not yet implemented*

## Purpose

Upload completed bronze Parquet files from local disk to GCS, transforming the
flat local path scheme into the Hive-partitioned scheme BigQuery requires for
partition pruning.

## Position in the DAG

```
bronze asset  →  upload asset  →  (BigQuery tables)
```

This is the cross-boundary handoff from the local pipeline to the cloud layer.

## Path Transformation

| Side | Pattern |
|---|---|
| Local input | `{bronze_root}/{year}.parquet` |
| GCS output | `gs://{bucket}/bronze/publication_year={year}/{year}.parquet` |

The file contents are unchanged; only the path scheme differs. The Hive prefix
exists solely for BigQuery partition pruning.

## Upload Scope

All years for which a bronze Parquet file exists on disk are uploaded. The
asset scans the bronze directory to derive the year list — no metadata passing
from the bronze asset. This keeps the upload asset self-contained and
independently runnable.

The in-flight 2026 file is treated identically to any other year — bronze's
contract is: file exists → year is ingested.

## Skip Logic (Idempotency)

A year is skipped if the GCS object already exists **and** its `updated`
metadata timestamp is ≥ the local file's `mtime`. Otherwise the file is
(re-)uploaded. This avoids redundant uploads on re-runs while ensuring stale
objects are refreshed.

## Progress Logging

Live per-file logging throughout the upload loop:

```
[upload] 1950  →  gs://…/publication_year=1950/1950.parquet  (skipped, up to date)
[upload] 1951  →  gs://…/publication_year=1951/1951.parquet  (uploaded, 1.2 MB)
…
```

At completion, a summary line reports total uploaded, skipped, and elapsed time.

## Upload Manifest

After all uploads complete, a manifest is written to GCS at:

```
gs://{bucket}/bronze/_UPLOAD_MANIFEST.parquet
```

One row per year. Columns:

| Column | Type | Notes |
|---|---|---|
| `publication_year` | int | |
| `gcs_path` | string | Full `gs://…` URI |
| `file_size_bytes` | int | |
| `uploaded_at` | timestamp | UTC timestamp of the last upload for this object |

The manifest is rewritten in full after each run and uploaded last, so its
presence signals a complete run.

## GCS Client

`google-cloud-storage` Python SDK. Authenticates via ADC (Application Default
Credentials); no key file.

## Tests

One test file. No cloud boundary crossed — GCS client is mocked.

Three cases for the skip logic:

| Case | Local mtime | GCS `updated` | Expected decision |
|---|---|---|---|
| Object newer | t | t + 1s | skip |
| Local newer | t | t - 1s | upload |
| Object absent | t | — | upload |

The test constructs a fake blob with a controllable `updated` attribute and
asserts the skip/upload decision. The GCS client itself (`bucket.blob`,
`blob.upload_from_filename`) is mocked — we are testing our logic, not the SDK.
