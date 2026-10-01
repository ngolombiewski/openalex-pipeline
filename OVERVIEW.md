# Project Overview

Derived from executable contents in `src/`, `tests/`, `dbt/`, and `terraform/`.
Source commit: `ef306b9c803bd71d4da071ef2379daee1f976bf0`.

## What This Is

A resumable OpenAlex works pipeline: year-sharded API extraction, local Parquet
bronze, GCS publication, and dbt analytics in BigQuery. Dagster coordinates local
refreshes and production warehouse builds. The analytical models measure AI's
share of the extracted computer-science corpus, citation age, and citation
concentration. Extraction accepts a configured filter; the analytics assume that
filter selects the intended CS corpus.

## Data Flow

```text
OpenAlex works API
  -> extract/{year}/page-*.jsonl + _YEAR_REPORT.json
  -> bronze/{year}.parquet + local _MANIFEST.parquet
  -> gs://{bucket}/bronze/publication_year={year}/{year}.parquet
     + gs://{bucket}/upload/_MANIFEST.parquet
  -> openalex_raw.bronze_external
  -> stg_works -> silver_works
                 -> gold_ai_share_by_year
                 -> gold_citation_age_by_year
                 -> gold_citation_gini_by_subfield
                 -> gold_citation_gini_by_group
```

Local paths sit under `OPENALEX_DATA_ROOT`. The bronze and upload manifests are
rebuilt projections of artifact state, not authorities for ingestion or upload
skip decisions. BigQuery reads the year objects through a Hive-partitioned
external table; dbt materializes all six models as native tables.

## Component Responsibilities

- **Extraction (`src/openalex_pipeline/extraction/`):** settings resolve the
  filter, inclusive year bounds, API key, and data root. The runner builds
  canonical queries with 21 selected columns and 200 records per page, processing
  years in ascending order. The connector owns HTTP retries; the worker owns
  pagination; storage owns all file I/O and resume classification.
- **Bronze (`src/openalex_pipeline/bronze/`):** ingest completed years under an
  explicit Polars schema, preserving eight nested fields as JSON strings and
  dates as strings. Reject null IDs, malformed inputs, and record-count
  divergence. Preserve duplicate IDs and report their excess count. Existing
  year Parquet files are skipped; the manifest rebuild still reads IDs and
  checks counts against available extraction reports.
- **Upload (`src/openalex_pipeline/upload/`):** discover numeric Parquet stems,
  transfer absent or older GCS objects, then write the upload manifest last.
  Skip when the object's server timestamp is at least the local file mtime.
  Cloud clients are injected into the runner; the CLI uses ADC.
- **Orchestration (`src/openalex_pipeline/orchestration/`):** wrap the three
  runners as dependent assets; serialize local mutations; execute durable
  invalidation requests; determine convergence and warehouse freshness from
  filesystem and cloud metadata. Importing definitions prepares a fresh dbt
  manifest under a separate lock, running `deps` if packages are absent and
  always running `parse` for the prod target.
- **Staging (`dbt/models/staging/`):** apply publication bounds and require both
  `is_retracted = false` and `is_paratext = false` (nulls also drop). Parse nested
  JSON and dates, then deduplicate IDs by descending parsed `updated_date`, nulls
  last. Staging is the parse-once warehouse boundary.
- **Silver (`dbt/models/silver/`):** preserve staging's row grain and add strict
  AI (subfield 1702) and broad AI (1702 or 1707) flags. Null subfields produce
  false flags and remain in the denominator. Carry the dimensions and measures
  needed by gold, including nested annual citation counts.
- **Gold (`dbt/models/gold/`):** Q1 produces publication-year shares for strict
  and broad AI, flagging 2026 as partial. Q2 produces citation-event-weighted
  age quartiles and shares aged at most 2, 5, and 10 years, by citation year and
  cited-work group (`ai`, `cv_pr`, `rest_cs`). Q3 measures concentration by
  publication cohort and cumulative citation window, primarily by subfield,
  with pooled groups as a secondary view. Outputs include Gini, zero share,
  cited-only Gini, top 1/5/10% citation shares, and publication-year diagnostics.
  Concentration metrics are null when the relevant citation total is zero.
- **Infrastructure (`terraform/`):** provision the EU bronze bucket, raw and
  separate prod/dev analytics datasets, the pinned external-table schema, and
  a dedicated impersonated dbt identity with query, dataset-write, and source-read
  permissions. Public bucket access is prevented; the bucket is protected from
  Terraform destruction.

## Contracts Between Components

**Extraction completion and resume.** `_META.json` stores query identity and the
first reported API count. Each page is atomically written before `_CURSOR.json`
advances; replay can overwrite the same page. `_YEAR_REPORT.json` is the
completion signal and wins over stale cursor state. A null cursor without a
report means finalization is still owed. Query mismatches and invalid recognized
file combinations raise typed errors. Expected-versus-fetched count differences
are recorded without blocking completion.

A zero-result year has one empty page. A trailing empty page is not written; an
empty page with a live cursor raises before any write. HTTP 429 produces a clean
partial run, while network failures, 403, and server failures receive bounded
backoff. Other diagnosed connector failures propagate as typed errors.

**Extraction to bronze.** A report with no page files is corrupt. A zero-byte
page in a multi-page year is corrupt. Completed reports in scope must agree on
the canonical query after masking their publication-year clause. Bronze writes
one Parquet per year via temporary file and rename. Its manifest is scoped to
the requested years and reasserts `records_fetched == bronze_row_count` wherever
both sides exist.

**Bronze to BigQuery.** The 21-column Polars schema and Terraform external-table
schema must agree in order and scalar types. Terraform omits `publication_year`
from the ordinary schema because Hive supplies that partition key. Nested
columns stay STRING until staging. The upload manifest lives outside the bronze
partition tree and records live object sizes and timestamps for uploaded and
skipped years alike.

Terraform ignores external-table schema changes to avoid Hive-induced drift;
deliberate schema revisions require explicit recreation. Its remote state lives
in the bronze bucket under `terraform/state`.

**Refresh and convergence.** A refresh request creates
`extract/_INVALIDATING_{year}` without deleting data. Extraction's next asset
compute validates all pending markers, deletes bronze first, then extraction,
then the marker, with directory fsyncs around completion. Invalid marker names,
symlinks, or out-of-range years raise. Convergence requires no pending marker,
complete extraction for every configured year, local Parquet, and sufficiently
fresh GCS objects.

The warehouse sensor requires a nonempty upload manifest with the pinned schema,
exactly one row per configured year, and non-null upload timestamps. Every dbt
relation must exist; tables must have modification timestamps. Warehouse data
is stale when the newest recorded upload is newer than the oldest model table.
Present views participate in existence checks only. Materializations other than
table/view raise.

**Analytical windows.** Default corpus bounds are 1950–2026. Q2 uses citation
years 2012–2025, positive counts, and nonnegative citation ages. Classification
refers to cited works; citing-work identity is unavailable here. Q3 uses cohorts
2012–2024 with windows from age 1 through the end of 2025. Its shared
`q3_paper_windows` macro retains zero-citation papers; publication-year citations
are diagnostics excluded from headline windows. Unclassified subfields remain
an explicit Q3 bucket. Gold tests reconcile cohort sizes, citations, cross-grain
outputs, and concentration identities.

## Execution & Verification

Extraction requires `OPENALEX_API_KEY`, `OPENALEX_FILTER`,
`OPENALEX_START_YEAR`, `OPENALEX_END_YEAR`, and `OPENALEX_DATA_ROOT`; its settings
also load `.env`. Orchestration additionally requires `OPENALEX_GCS_BUCKET` and
`OPENALEX_GCP_PROJECT`. The filter excludes the publication-year clause, which
the runner appends. Bronze/upload CLIs read their defaults from process
environment and allow explicit root/bucket overrides.

```sh
uv run python -m openalex_pipeline.extraction
uv run python -m openalex_pipeline.bronze --years 1950:2026
uv run python -m openalex_pipeline.upload
uv run pytest
uv run dbt build --project-dir dbt --profiles-dir dbt --target dev \
  --vars '{year_min: 2012, year_max: 2016}'
```

The dbt default target is `dev` (`openalex_analytics_dev`); prod is
`openalex_analytics`. Selecting dev alone does not narrow the default corpus
bounds. Both profiles use EU, four threads, service-account impersonation, and a
100 GiB per-job billing limit. Staging and silver are partitioned by publication
year and clustered by primary subfield. Gold tables are unpartitioned.

Dagster's `local_sweep` runs extraction, bronze, and upload daily at 04:00 in
`Europe/Berlin`. `invalidate_refresh_year` requests refresh of the configured **end year**
at 03:00 on the first of each month. The warehouse sensor evaluates at a minimum
four-hour interval and requests prod builds only after convergence. It skips
active warehouse runs and busy local writers, keys requests by newest upload
time, and tags builds for at most three retries. Both schedules and the sensor
default to RUNNING: starting Dagster activates production automation.

Python tests exercise resume ordering, corruption, schema mirrors, idempotent
bronze/upload behavior, locks, interrupted invalidation, cloud metadata, sensor
requests, and definition preparation. dbt schema and singular tests cover keys,
row preservation, parsing, classification shares, citation-source validity,
complete output grids, and metric reconciliation. Some source-quality checks
warn, including missing subfields and negative-age citation entries. Definition
tests import the module that prepares dbt artifacts; cloud-facing unit tests use
fakes. These are verification entry points, not a claim that checks ran during
this documentation refresh.

## Architectural Constraints

Artifact presence is the local completion authority. Manifests are derived;
Dagster records scheduling and run history but does not replace file-based
pipeline state. One landing zone holds one query/corpus. Schema inference and
bronze deduplication are deliberately absent; typing and classification belong
to explicit downstream boundaries. Known failures receive specific exceptions;
unexpected failures generally propagate.

The lock is a POSIX `flock` beside the local layers. Dagster writers take it
exclusively per compute; sensor readers try a nonblocking shared lock. This
assumes cooperating processes on a shared local filesystem. Infrastructure and
dbt profiles contain project-specific names and impersonation addresses.

## Known Limitations & Open Questions

- Refresh automation targets only the configured end year; it does not advance
  that setting with the calendar or refresh historical citation histories. Q2
  and Q3 snapshot bounds are independent of corpus bounds and need deliberate
  full-corpus refresh and reconciliation before advancing.
- Upload freshness uses timestamps, not content hashes. Standalone layer CLIs
  do not acquire the orchestration lock, and the lock is not held across an
  entire sweep or warehouse build. There is no atomic multi-year cloud snapshot.
- Warehouse freshness detects missing relations and upload changes, not model
  code changes or whether the last build's tests passed. Reusing an upload-time
  run key does not request a new independent sensor run after retries exhaust.
- Completed markers and existing Parquet files are trusted within their layer.
  Count checks cannot detect all content corruption. A crash during initial
  metadata setup before the first page can leave a layout that raises corruption
  rather than resuming automatically.
- The rolling annual citation history constrains Q3's cohort floor. Q2 dev
  slices omit older cited works and cannot preview full-corpus age statistics.
  Annual counts support discrete year ages, not within-year timing or inference
  about citing-work fields.
- dbt tables rebuild rather than incrementally merge. Source-derived defaults
  and tests establish intended behavior; they do not establish current deployed
  infrastructure, warehouse results, or live operational health.
