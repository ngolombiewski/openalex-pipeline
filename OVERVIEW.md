# Project Overview

Derived afresh from executable source, configuration, and tests in `src/`,
`tests/`, `dbt/`, `terraform/`, `tools/`, `dashboard/`, and `.github/workflows/`,
plus the root runtime configuration.
Source commit: `77ede118d9a242a9cd5213176eca1ffd810bf78f`.

## What This Is

An OpenAlex works pipeline with resumable year-sharded extraction, typed local
Parquet, GCS publication, and dbt analytics in BigQuery. Dagster coordinates
refreshes and production warehouse builds; Terraform defines cloud storage,
warehouse datasets, the external source table, and service-account permissions.

Four gold tables answer three questions about computer-science research: AI's
share of output, the age of work receiving citations, and citation concentration.
Extraction accepts a configured filter; the analytical layer assumes that it
selects the intended CS corpus. An Astro dashboard presents the results as a
static visual essay built from committed gold snapshots. Ingestion, warehouse
updates, snapshot export, and website publication are separate operations.

## Data Flow

```text
OpenAlex works API
  -> extract/{year}/page-*.jsonl + _YEAR_REPORT.json
  -> bronze/{year}.parquet + bronze/_MANIFEST.parquet
  -> gs://{bucket}/bronze/publication_year={year}/{year}.parquet
     + gs://{bucket}/upload/_MANIFEST.parquet
  -> openalex_raw.bronze_external
  -> stg_works -> silver_works
                 -> gold_ai_share_by_year
                 -> gold_citation_age_by_year
                 -> gold_citation_gini_by_subfield
                 -> gold_citation_gini_by_group
  -> manual export: dashboard/data/{four relations}.json + snapshot.json
  -> Astro static build: HTML + CSS + browser charts
  -> manual publication of a selected commit to GitHub Pages
```

Local extraction and bronze paths sit under `OPENALEX_DATA_ROOT`. File presence
and completion reports govern local progress. Both manifests are derived
inventories; neither drives its layer's skip decisions. BigQuery reads the GCS
objects through a Hive-partitioned external table. All six dbt models are native
tables; staging is the boundary after which JSON and dates are already parsed.

## Component Responsibilities

- **Extraction (`src/openalex_pipeline/extraction/`):** settings load the API
  key, filter, inclusive years, and data root. The runner constructs canonical
  queries with 21 pinned columns and 200 records per page, then processes years
  in ascending order. The connector owns HTTP retries, the worker pagination,
  and storage all filesystem operations and resume classification.
- **Bronze (`src/openalex_pipeline/bronze/`):** convert completed shards using
  an explicit Polars schema. Preserve eight nested fields as JSON strings and
  dates as strings. Reject malformed input, null IDs, and count divergence;
  retain duplicate IDs and report their excess count. Rebuild the scoped local
  manifest from extraction reports and Parquet contents.
- **Upload (`src/openalex_pipeline/upload/`):** discover numeric Parquet stems,
  upload absent or older GCS objects, and publish the upload manifest last.
  Record remote size and update time for both transferred and skipped objects.
  The runner accepts an injected bucket; the CLI constructs it using ADC.
- **Orchestration (`src/openalex_pipeline/orchestration/`):** expose the runners
  and dbt models as dependent Dagster assets. Serialize cooperating local
  writers, request and execute durable invalidations, check convergence, and
  trigger prod builds when warehouse tables lag uploaded data.
- **Staging (`dbt/models/staging/`):** apply publication bounds and require
  `is_retracted = false` and `is_paratext = false`, dropping null statuses too.
  Parse nested fields and dates, then deduplicate work IDs by parsed
  `updated_date` descending, nulls last.
- **Silver (`dbt/models/silver/`):** preserve staging's rows, project analytical
  columns, and classify strict AI as subfield 1702 and broad AI as 1702 or 1707.
  Null subfields receive false flags and remain in the denominator.
- **Gold (`dbt/models/gold/`):** aggregate output shares by publication year;
  citation-event-weighted age distributions by citation year and cited group;
  and cumulative citation concentration by publication cohort, window, and
  either subfield or pooled cited group. All four models enforce column/type
  contracts.
- **Snapshot exporter (`tools/export_dashboard_snapshot.py`):** manually read
  the four prod gold relations with pinned columns and grain ordering. Check
  bounds, safe integers, and concurrent table modification before replacing
  the snapshot directory. Record source tables and modification times, export
  time, bounds, row counts, and an explicitly supplied pipeline revision.
- **Dashboard (`dashboard/`):** validate the committed snapshot at build time,
  select fixed analytical views, check the authored claims, and render a single
  page with three Observable Plot charts, detail tables, methods, and provenance.
  Astro emits static assets; browser code draws responsive charts from selected
  display data. No warehouse connection or application server is needed.
- **Infrastructure (`terraform/`):** define the EU bronze bucket, raw and
  separate dev/prod analytics datasets, explicit external-table schema, and dbt
  identity with query, source-read, and dataset-write permissions. The bucket
  prevents public access and has a Terraform `prevent_destroy` guard.

## Contracts Between Components

**Extraction state.** A year is fresh, in progress, or complete. `_META.json`
records query identity and the first API count. Identity excludes the API key
and cursor. `_YEAR_REPORT.json` is the completion signal and takes precedence
over stale cursor state. Existing query identity must match the requested query.
Recognized invalid file combinations raise typed corruption errors.

Each page is written through a temporary file and atomic replacement before
`_CURSOR.json` advances, so an interrupted update can replay the same page.
A null cursor without a report means finalization is still owed. Finalization
counts persisted records and records any difference from the first API count
without rejecting completion. A zero-result year contains one empty page;
trailing empty pages are omitted. An empty page with a live cursor raises
before writing.

The connector uses a 30-second timeout and five total attempts with exponential
backoff for connection failures, timeouts, 403, and server failures. HTTP 429
ends the runner cleanly with a partial report. Other diagnosed failures raise
specific exceptions; unexpected errors propagate.

**Extraction to bronze.** When ingestion is needed, a completion report without
pages is corrupt, as is an empty page in a multi-page shard. Completed reports in scope must agree on
query identity after masking their publication-year clause. Existing year
Parquet files skip ingestion; new files are written through temporary files and
rename. Bronze retains duplicates for staging to resolve. Its manifest rebuild
rereads Parquet IDs, derives row and duplicate counts, and reasserts
`records_fetched == bronze_row_count` wherever an extraction report exists.
A zero-result shard produces a zero-row Parquet with the full schema.

**Bronze to warehouse.** The ordered 21-column bronze schema must match the
Terraform external-table schema except for `publication_year`, which Hive
supplies from the object path. Nested columns remain STRING until staging.
Upload skips an object only when its server update time is at least the local
Parquet mtime. The upload manifest is outside the bronze partition tree and
contains live remote metadata. A failed upload run can leave the previous
manifest in place.

**Refresh and readiness.** An invalidation request creates
`extract/_INVALIDATING_{year}` for a completed shard without deleting data.
Extraction's next asset compute validates every pending marker, then deletes
local bronze, the extraction directory, and finally the marker, in that order,
with directory fsyncs around completion. Malformed markers, symlinks, and years
outside configured bounds raise. Remote objects are replaced by subsequent
uploads, not deleted by invalidation.

Convergence requires no pending invalidation, complete query-matching extraction
for every configured year, local Parquet, and GCS objects at least as fresh as
those files. The warehouse sensor then requires an upload manifest with the
pinned schema, exactly one row per configured year, and non-null upload times.
A missing dbt relation or a newest upload newer than the oldest model table
makes the warehouse stale. Views participate only in existence checks; missing
table timestamps and unsupported materializations raise.

**Analytical grains and windows.** Defaults are publication years 1950–2026,
with 2026 flagged partial. Q1 has one row per publication year and strict/broad
variant. Both use all silver works in that year as their denominator.

Q2 spans citation years 2012–2025 and groups cited works into `ai`, `cv_pr`, and
`rest_cs`. Positive annual counts at nonnegative ages contribute citation events;
age is citation year minus publication year. Weighted quartiles and shares at
ages at most 2, 5, and 10 describe the work receiving citations, not the identity
or discipline of citing works.

Q3 spans publication cohorts 2012–2024 and cumulative windows from age 1 through
the end of 2025. The shared `q3_paper_windows` macro retains zero-citation works.
Publication-year citations are separate diagnostics, excluded from headline
windows. Subfield output retains an explicit unclassified bucket; pooled groups
are calculated separately. Measures include all-paper and cited-only Gini,
uncited share, and top 1/5/10% citation shares. Top-k cutoffs use
`ceil(k * n_papers)` over all cohort papers. Ratios with zero citation
denominators are null, not zero.

**Warehouse to snapshot.** Export queries use ADC impersonation, EU location,
and a 1 GiB billed-bytes limit each. Column lists must match, relations must be
nonempty, integers must fit JavaScript's safe range, and data extents and
partial-year flags must agree with the pinned dbt variables. A change in any
source table's modification time during export aborts before snapshot writing.
The required revision argument accepts `unknown`; the exporter never substitutes
its own commit.

Files are assembled in a temporary sibling directory. Replacement moves the old
directory aside, then renames the new one into place. An interruption between
these renames can leave `dashboard/data/` absent; it cannot expose a partially
assembled directory. This is not a transaction across warehouse tables.

**Snapshot to page.** `parseSnapshot` checks exact row columns, types,
nullability, grain uniqueness, nonempty relations, recorded counts and bounds,
and completeness of the fixed views. Those views are Q1 from 1980, Q2 across
its recorded citation years, and Q3's classified subfields for the 2020 cohort
at age 5 (citations in 2021–2025). Raw relations remain in build-time imports.
Known boundary failures raise `SnapshotDataError`; missing or malformed JSON
fails earlier in the bundler.

Section functions also check the claims used in their prose: Q1's trough, rise,
and complete-year record comparisons; Q2's falling and converging median ages;
and Q3's relative reach and concentration comparisons. Unsupported claims stop
the build for content review. The page formats published measures rather than
recomputing them. Undefined Q3 scatter values remain in tables but are omitted
from the chart with an omission count. Provenance rendering requires UTC export
time and fully qualified production source-table names.

## Execution & Verification

Python requires 3.12+ and uses `uv`. Extraction settings require
`OPENALEX_API_KEY`, `OPENALEX_FILTER`, `OPENALEX_START_YEAR`,
`OPENALEX_END_YEAR`, and `OPENALEX_DATA_ROOT`. The filter omits the
publication-year clause, which the runner appends. Extraction settings load
`.env`; bronze/upload CLIs read process environment and support explicit path
or bucket overrides. Orchestration also requires `OPENALEX_GCS_BUCKET` and
`OPENALEX_GCP_PROJECT`. The exporter additionally requires
`OPENALEX_DBT_SERVICE_ACCOUNT` in its process environment.

Standalone entry points, with configuration and credentials already loaded:

```sh
uv run python -m openalex_pipeline.extraction
uv run python -m openalex_pipeline.bronze --years 1950:2026
uv run python -m openalex_pipeline.upload
uv run dbt build --project-dir dbt --profiles-dir dbt --target dev \
  --vars '{year_min: 2012, year_max: 2016}'
```

The dbt default target is `dev` (`openalex_analytics_dev`); prod is
`openalex_analytics`. Target selection does not narrow publication bounds.
Both profiles use EU, four threads, service-account impersonation, and a
100 GiB per-query billing limit. Staging and silver use integer publication-year
partitions and subfield clustering; gold tables are unpartitioned.

Dagster's `local_sweep` runs daily at 04:00 Europe/Berlin. Monthly invalidation
runs at 03:00 on day 1 and targets the configured end year. The warehouse sensor
has a four-hour minimum interval, skips active warehouse runs and busy local
writers, and requests prod builds keyed by newest upload time with at most
three retries. Both schedules and the sensor default to RUNNING: starting
Dagster activates production automation. Importing its definitions prepares a
prod dbt manifest under `dbt/.prepare.lock`, installing missing dbt packages and
always parsing; it does not build tables at import. `.envrc` initializes the
local Dagster instance and links the tracked retry configuration.

Python CI installs locked dependencies, runs Ruff lint/format checks, Pyright,
and pytest, then dbt dependency installation, parsing, and Dagster definitions
validation. It uses a placeholder GCP project without cloud authentication.
Tests exercise state transitions, schema mirrors, corruption, idempotence,
locks, invalidation interruptions, cloud metadata, sensor decisions, and snapshot
export. dbt fixture unit tests and warehouse data tests run during `dbt build`;
they cover classification, weighted ages, concentration calculations, output
grids, reconciliation, and metric identities. Some source-quality checks warn
rather than fail, including missing subfields and negative citation ages.

The dashboard pins Node in `.node-version` and npm dependencies in its lockfile.
From `dashboard/`, `npm ci`, `npm run check`, `npm test`, and `npm run build`
need no pipeline credentials. Tests cover the snapshot boundary, provenance,
claim failures and thresholds, chart/table agreement, and formatting. Dashboard
CI runs these checks for relevant changes. The Pages workflow is dispatched
manually with a full commit SHA, checks and builds that commit, then deploys its
static artifact. Neither CI workflow exports warehouse data. These are
verification entry points, not evidence of a live deployment or a test run
during this documentation refresh.

## Architectural Constraints

The filesystem is the authority for local pipeline state. Manifests are
projections, and Dagster history does not replace artifact completion signals.
A landing zone holds one query/corpus. Schema inference, bronze deduplication,
and implicit repair of diagnosed corruption are absent by design. Each layer
trusts the assertions made by the layer below within its scope.

Dagster local writers take an exclusive POSIX `flock` per compute; sensor
convergence checks take a nonblocking shared lock. This assumes cooperating
processes on one shared local filesystem. A separate lock protects dbt manifest
preparation. Neither is a distributed lock.

Infrastructure contains deployment-specific bucket/backend names and
impersonation identities. Terraform state resides in the bronze bucket under
`terraform/state`. External-table schema changes are ignored to avoid Hive
schema drift; intentional revisions require explicit table recreation. The
static site's base path and hosting origin are also pinned in configuration.

## Known Limitations & Open Questions

- Monthly refresh affects only the configured end year. It neither advances
  that setting with the calendar nor updates historical works' citation
  histories. Corpus, Q2, and Q3 bounds are independent; advancing citation
  analyses requires a deliberate full-corpus refresh and reconciliation.
- Annual citation history has a rolling horizon. Older Q3 cohorts may become
  unrebuildable from later API responses. Frozen dashboard aggregates preserve
  published outputs, not the source records needed to regenerate them.
- Upload freshness compares timestamps, not content hashes. Standalone CLIs
  do not take the orchestration lock; locks do not span a whole sweep or
  warehouse build. There is no atomic multi-year cloud or warehouse snapshot.
- Warehouse freshness detects missing relations and newer uploads, not model
  code changes or successful tests. A reused upload-time run key does not
  request another independent sensor run after retries are exhausted.
- Completion reports and existing Parquet files are trusted within their
  layers. Counts cannot detect all content corruption. Interrupted extraction
  initialization before the first page can leave a state that raises rather
  than resuming. Atomic file replacement does not imply universal crash recovery.
- A reduced dev publication slice omits older cited works and cannot reproduce
  full-corpus Q2 age statistics. Calendar-year citation counts do not provide
  within-year timing or citing-work identities. Null subfields are retained
  in warehouse denominators but excluded from the dashboard's Q3 comparison.
- dbt rebuilds tables rather than incrementally merging them. Snapshot export
  and website release are manual, and the dashboard's views and narrative are
  deliberately fixed. Source inspection establishes these behaviors, not
  deployed infrastructure state, live operational health, or current results.
