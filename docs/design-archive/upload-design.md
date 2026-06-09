# GCS Upload Asset — Design

*Status: Implemented*

## Purpose

Upload completed bronze Parquet files from local disk to GCS, transforming the
flat local path scheme into the Hive-partitioned scheme BigQuery requires for
partition pruning.

## Position in the DAG

```
bronze asset  →  upload asset  →  (BigQuery tables)
```

This is the cross-boundary handoff from the local pipeline to the cloud layer.

## Module Shape

A plain CLI module, `python -m openalex_pipeline.upload`, mirroring extraction
and bronze. It will eventually become a Dagster asset like the others; for now
it is a regular module. No Dagster wiring yet.

## Configuration

| Input | Source | Default |
|---|---|---|
| `bronze_root` | `--bronze-root`, else `{OPENALEX_DATA_ROOT}/bronze` | — |
| `bucket` | `--bucket`, else `OPENALEX_GCS_BUCKET` | - |

Mirrors bronze's resolution pattern (explicit flag wins, then env). We don't
hardcode defaults: If neither flag nor env var is present, we raise.

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

The scan matches `{year}.parquet` where the stem is all digits. It deliberately
excludes the derived `_MANIFEST.parquet` and any transient `*.tmp` files that
may exist mid-write in the bronze directory.

The in-flight 2026 file is treated identically to any other year — bronze's
contract is: file exists → year is ingested.

## Skip Logic (Idempotency)

A year is skipped if the GCS object already exists **and** its `updated`
metadata timestamp is ≥ the local file's `mtime`. Otherwise the file is
(re-)uploaded. This avoids redundant uploads on re-runs while ensuring stale
objects are refreshed.

The comparison crosses two clock representations and must convert explicitly:
the local `mtime` is a naive float from `os.stat`, while the blob's `updated`
is a timezone-aware UTC datetime. The decision compares
`datetime.fromtimestamp(mtime, tz=UTC)` against `blob.updated`; both sides are
tz-aware UTC. (Bronze never rewrites an already-ingested year's Parquet, so
mtimes are stable across bronze re-runs and the skip logic does not spuriously
re-upload.)

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
gs://{bucket}/upload/_MANIFEST.parquet
```

It sits in its own `upload/` prefix, a sibling to `bronze/` — deliberately
outside the `bronze/publication_year=*/` tree that BigQuery globs as
Hive-partitioned, so it can never be mistaken for a partition.

One row per year. Columns:

| Column | Type | Notes |
|---|---|---|
| `publication_year` | int | |
| `gcs_path` | string | Full `gs://…` URI |
| `file_size_bytes` | int | From the GCS blob (`blob.size`) |
| `uploaded_at` | timestamp | The blob's server-side `updated`, UTC |

**Purely derived.** The manifest is never read back; it is rebuilt wholesale
each run from live GCS blob metadata, matching the bronze manifest's
"derived, never authoritative" principle. Every row — whether its year was
uploaded or skipped this run — is sourced uniformly from the blob: `size` and
`updated`. For skipped years the blob was already fetched for the skip check;
for uploaded years a `blob.reload()` after upload yields the authoritative
server values. This means `uploaded_at` reflects GCS's clock, not a local
`now()`. The manifest is rewritten in full and uploaded last, so its presence
signals a complete run.

## GCS Client

`google-cloud-storage` Python SDK (a new project dependency). Authenticates via
ADC (Application Default Credentials); no key file.

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
