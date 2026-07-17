# Orchestration design — Dagster

*Status: implemented, pending review. Supersedes the scope note in STATE.md
step 9 and revises the automation boundary recorded in ARCHITECTURE.md
(2026-07-07).*

## 1. Purpose and honest scope

The pipeline does not strictly need an orchestrator: the corpus is static,
every layer is an idempotent sweep, and a human running three commands is a
working schedule. Orchestration is here for two reasons, in this order:

1. **Demonstration.** The project is a DE Zoomcamp capstone; an orchestrated,
   end-to-end asset graph with visible lineage is a deliverable in itself.
2. **One real operational need:** the current year (2026) is unstable and
   should be re-pulled on a cadence — the *refresh* — and the warehouse
   rebuilt when new data lands.

The design keeps automation minimal and problem-driven: everything Dagster
does maps to one of those two reasons. No ceremony.

## 2. Design principles (project principles, applied)

- **Filesystem (and cloud object/table state) stays the source of truth.**
  Dagster's event log is *advisory*: a materialization record is a log entry,
  never a precondition. Wiping `DAGSTER_HOME` loses history, never
  correctness. No orchestration decision may depend on Dagster's own records;
  every trigger predicate derives from filesystem, GCS, or BigQuery metadata.
- **The runners stay authoritative.** Assets are thin wrappers around the
  existing `run()` entry points. Skip/resume logic lives in the modules, as
  today; Dagster never re-implements or second-guesses it.
- **Sweep over cascade.** Because every runner is a whole-corpus idempotent
  sweep with filesystem completion signals, "run the chain daily" *is* the
  per-year event cascade: extraction stops cleanly at the daily API limit,
  bronze ingests whatever newly became READY, upload pushes whatever bronze
  newly produced. Bootstrap-from-scratch and steady-state refresh are the same
  job at different points of convergence. No partitioned assets, no per-year
  eventing (decided 2026-07-08; partitioned assets would create a second
  completion ledger that can drift from the manifests).

## 3. The asset graph

All code lives in `src/openalex_pipeline/orchestration/`. One `Definitions`
object; loadable by `dagster dev` and importable in tests.

Three unpartitioned software-defined assets wrap the local chain:

| Asset key | Wraps | Output metadata (advisory) |
|---|---|---|
| `extracted_jsonl` | `extraction.runner.run(Settings())` | `status`, `stopped_year`, `years_completed` / `years_skipped`, `completed_shard_records_total`, first/last outcome year |
| `bronze_parquet` | `bronze.runner.run(extract_root, bronze_root, years)` | `years_configured`, `manifest_years_total`, manifest status counts |
| `bronze_gcs` | `upload.runner.run(bronze_root, bucket)` | `years_considered`, uploaded/skipped counts, `bytes_uploaded` for uploads performed this run |

Dependencies: `extracted_jsonl → bronze_parquet → bronze_gcs`.

Notes:

- **`stopped_daily_limit` is a success, not a failure.** The extraction runner
  returns it as a clean outcome; the asset materializes successfully with
  `status` in its metadata. Downstream assets still run (they sweep whatever
  is READY). Convergence — not asset success — gates the warehouse build (§5).
- Configuration comes from the existing env vars (`OPENALEX_*` via
  `Settings` / `.env`); no Dagster-side duplication of config. The GCS
  `Bucket` is constructed in a small Dagster resource — the same injection
  seam the upload module already exposes.
- Typed pipeline exceptions propagate and fail the run loudly, as everywhere
  else.
- Extraction's `completed_shard_records_total` is explicitly a lifetime state
  total for the completed outcomes visible to the invocation, including
  persisted counts for skipped shards. It is not a per-run extraction delta.
  Upload's `bytes_uploaded` is a true per-run transfer count and excludes
  skipped objects.

The dbt models become assets via **`dagster-dbt`** (`@dbt_assets` over the
project's manifest), which surfaces every model and test with real lineage.
The dbt source `bronze_external` is mapped to the `bronze_gcs` asset key so
the graph is connected end to end:

```
extracted_jsonl → bronze_parquet → bronze_gcs → stg_works → silver_works → gold_*
```

**Dagster only ever runs dbt with the `prod` target pinned on its resource.**
The dev target remains the
manual CLI loop it is today; orchestrating dev builds is YAGNI. dbt tests run
as part of `dbt build` and a test failure fails the run — same semantics as
the manual workflow.

## 4. Jobs and schedules

Two jobs, two schedules, one sensor. That is the entire automation surface.

### 4a. `local_sweep` — daily

Materializes `extracted_jsonl → bronze_parquet → bronze_gcs` in order.
Scheduled **daily**. Behavior by pipeline state:

- **Steady state (converged, nothing invalidated):** extraction classifies
  every year COMPLETE and skips; bronze and upload all-skip. The tick is a
  no-op in seconds.
- **Refresh in flight:** extraction re-pulls the invalidated year (resuming
  across ticks if a pull ever straddles the ~2 M records/day API cap); once
  the year finalizes, bronze re-ingests it and upload overwrites the stale GCS
  shard (`should_skip` is mtime-based, so overwrite is the existing behavior —
  no new code).
- **Bootstrap from scratch:** weeks of `stopped_daily_limit` ticks accumulate
  the corpus; the same job, no special casing.

### 4b. `invalidate_refresh_year` — monthly

An op job (it requests destructive work, so it is an operation rather than an
asset) that durably writes an invalidation tombstone for the refresh target
(§6). It deletes nothing. Scheduled **monthly**. The refresh target is
`Settings().end_year` — the same pin as the corpus bound. (Year rollover —
bumping `OPENALEX_END_YEAR` and the dbt corpus-bounds vars in January —
remains the manual config change it already is; this design does not touch it.)

Two schedules instead of one self-timing job, deliberately: the monthly
cadence lives in schedule config where it is explicit and editable, rather
than being inferred from a GCS blob timestamp inside a guard. The
invalidation guard then only checks *completeness*, not age.

### 4c. `warehouse_build` + staleness sensor

`warehouse_build` materializes all dbt assets (`dbt build -t prod`). It is
triggered by a **sensor**, not a schedule, and the sensor's predicate is
derived entirely from system state (§5): it fires when the pipeline is
*converged* and the warehouse is *stale*. Consequences:

- dbt runs only after the local chain has fully closed over a refresh — never
  on a half-refreshed corpus. (During a refresh the warehouse stays fully
  queryable: the old GCS shard serves the external table until upload
  atomically overwrites it, and the native tables are untouched until the
  rebuild.)
- The sensor emits one stable run key per latest upload timestamp and tags the
  request with `dagster/max_retries=3`. Root `dagster.yaml` enables automatic
  retries, giving the initial launch plus at most three immediate re-executions
  (four total attempts). A deterministic failure therefore cannot trigger an
  unlimited series of ~43 GiB builds. After exhaustion the stable key stays
  deduplicated and the warehouse remains visibly stale; a later upload gets a
  new key and a fresh bounded budget. The sensor also skips while a build is
  queued or running and keeps its four-hour minimum evaluation interval.
- Retry bookkeeping is advisory Dagster state. Wiping `DAGSTER_HOME` may
  forget a run key and permit up to four extra attempts, but it cannot make
  stale warehouse data appear fresh: correctness still derives from
  filesystem, GCS, and BigQuery state.
- Bootstrap gets the right behavior for free: the first converged tick
  triggers the first warehouse build; nothing builds over a partial corpus.

Cost note: a full prod rebuild bills ~43 GiB. The sensor fires roughly once
per monthly refresh, comfortably inside the BigQuery free tier.

## 5. Convergence and staleness predicates

Two pure functions in `orchestration/` (e.g. `convergence.py`), fully
unit-testable, no Dagster imports:

**Converged** — "another sweep would change nothing":

1. Scan `{extract_root}/_INVALIDATING_*` first. A valid in-scope tombstone
   means pending work and returns false. A malformed or out-of-bounds suffix is
   `TombstoneCorruption`, never silently reduced to non-convergence.
2. Every year in `[start_year, end_year]` has a complete extraction landing
   zone. The predicate constructs the current `canonical_query(filter, year)`
   and calls the extraction layer's public `classify_year`; query mismatch and
   corrupt layouts therefore propagate loudly.
3. Every year's bronze parquet exists. Freshness relative to extraction is
   already asserted by bronze's manifest rebuild
   (`records_fetched == bronze_row_count`), so orchestration trusts that layer.
4. GCS is closed over local: for every year, the existing
   `upload.core.should_skip(local_mtime, blob_updated)` returns true. GCS year
   metadata is collected in one `list_blobs(prefix="bronze/")` pass.

The sensor holds the shared local-data lock (§6) across GCS metadata collection
and this predicate, so the local mtimes and cloud comparison are a coherent
read. It releases the lock before cloud-only manifest and warehouse checks.

**Upload-manifest input** is a strict contract at convergence. The object must
exist, be readable Parquet with exactly `UPLOAD_MANIFEST_SCHEMA`, be non-empty,
contain each configured year exactly once and no others, and contain no null
`uploaded_at`. Diagnosed absence (`NotFound`), Parquet parse failure, and
validation errors become `UploadManifestInvalid`; authentication, network, and
unexpected SDK failures propagate untouched.

**Warehouse stale** has two tiers derived from the current dbt manifest:

- every model materialized as `table` or `view` must exist in the prod
  dataset; a missing relation is stale;
- freshness timestamps apply only to tables:
  `max(uploaded_at) > min(modified over table-materialized models)`.

Views read their current dependencies and are not data-bearing, so their
timestamps do not participate; a present view with no useful `modified`
timestamp is complete. A present table without `modified` cannot establish
freshness and raises `WarehouseMetadataInvalid`. The manifest reader returns
immutable relation specs (name + materialization) and rejects any physical
materialization other than this pipeline's pinned `table` and `view`.

Requiring every relation prevents a missing terminal view from being hidden;
using the minimum across every table prevents a partial dependency-ordered dbt
build from making one upstream sentinel look fresh. A build that replaces all
tables but then fails a deterministic test may read as fresh; bounded retries
cannot repair that case, and the failed Dagster run remains the loud signal.

The sensor evaluates `converged AND stale`. Each tick uses local stat calls,
one GCS object listing, one strict manifest read, and BigQuery metadata lookups.

## 6. Invalidation protocol and local serialization

Invalidation is a request/executor protocol so interruption can never leave a
re-extracted year beside stale bronze parquet.

**Request — `request_year_invalidation(extract_root, year, query)`:**

- Check an existing `{extract_root}/_INVALIDATING_{year}` first and report
  `skipped_pending`, even if the year directory is already absent.
- An absent year directory reports `skipped_absent`. An existing non-COMPLETE
  year reports `skipped_in_progress`. Corrupt extraction state and query
  mismatch propagate from `classify_year`.
- For a COMPLETE year, atomically create an **empty** tombstone with `O_EXCL`;
  fsync the marker and `extract_root`, then report `requested`. The request
  deletes nothing.

**Executor —
`resume_pending_invalidations(extract_root, bronze_root, expected_years)`:**

- Called only at the top of `extracted_jsonl`, before the extraction runner.
  It validates every tombstone suffix against explicit configured bounds before
  deleting anything; markers must use the canonical integer spelling and be
  regular files. Malformed/out-of-scope markers raise
  `TombstoneCorruption`.
- Presence authorizes unconditional recovery from every interruption point:
  delete `{bronze_root}/{year}.parquet` if present, then
  `{extract_root}/{year}/` if present, fsync each existing parent, remove the
  tombstone, and fsync `extract_root` again. One immutable result per marker
  reports which artifacts actually existed and were deleted.
- GCS is deliberately untouched. It continues serving the old shard until the
  refreshed local parquet is uploaded, and its older timestamp makes the
  existing uploader overwrite it. Bronze/upload manifests remain derived and
  are rebuilt by their runners.

Tombstones are invisible to the underlying discovery contracts: extraction
only considers numeric year directories, and bronze upload discovers only
all-digit parquet stems.

**Filesystem lock.** Every Dagster compute that reads or writes the local chain
(`extracted_jsonl`, `bronze_parquet`, `bronze_gcs`, and the invalidation
request op) holds blocking `LOCK_EX` on
`{OPENALEX_DATA_ROOT}/.orchestration.lock` for its complete execution. The
data root is created before opening the lock, and kernel process teardown
releases it. Separate asset runs may interleave only between computes; they
cannot overlap local reads/writes.

The sensor attempts `LOCK_SH | LOCK_NB`. If a writer owns the lock it returns
`SkipReason("local pipeline mutation in progress")` immediately. If acquired,
the shared lock covers GCS-year collection plus convergence, preventing a
writer from landing a tombstone or deleting local artifacts mid-read. Writers
block briefly behind this shared reader.

Direct CLI invocations of extraction, bronze, or upload bypass the
orchestration-only lock. That pre-existing operational exposure is accepted:
do not run those commands concurrently with Dagster automation. A monthly
request that encounters a target already in progress is also deliberately
skipped, deferring that refresh to the next cadence rather than deleting a
partial pull.

## 7. Dagster instance state

Tracked root `dagster.yaml` is canonical configuration and enables automatic
run retries. `DAGSTER_HOME` is the separate, wholly gitignored in-repo
`.dagster/` advisory state directory. On every direnv load, `.envrc` exports
its **absolute** path, creates it, and refreshes
`.dagster/dagster.yaml -> ../dagster.yaml`. Editing `.envrc` requires
`direnv allow`; after intentionally clearing `.dagster/`, run
`direnv reload` before restarting Dagster. Deleting history can forget run
keys/retry counts but never removes the tracked correctness configuration.

Definitions startup has one deterministic manifest contract for every launch
mode. Importing `orchestration.definitions`:

1. acquires blocking `LOCK_EX` on the dedicated `dbt/.prepare.lock`;
2. runs `dbt deps` if `dbt/dbt_packages/` is absent;
3. always runs `dbt parse` with project directory, profiles directory, and
   `prod` target pinned; and only then lets `@dbt_assets` read the manifest.

The separate preparation lock prevents daemon and webserver processes from
writing a torn `dbt/target/manifest.json`. Module caching bounds preparation
to once per definitions process, while every process restart refreshes it.
Import therefore hard-requires the direnv-active environment (notably
`OPENALEX_GCP_PROJECT`) and costs roughly one dbt parse; failure aborts the
import loudly. There is no separate packaging step. Package changes still
require an explicit `dbt deps` or removal of `dbt_packages/`; the lockfile
remains the dependency contract.

All three automations — daily local sweep, monthly invalidation request, and
warehouse sensor — default to **RUNNING**. Starting Dagster is starting the
production automation; `dagster dev` is not a harmless graph viewer. Supported
launches are `dagster dev` or separate `dagster-daemon` plus webserver
processes, always from a direnv-active repository shell. The
`[tool.dagster]` block in `pyproject.toml` pins the definitions module and
code-location name for bare CLI launch.

The daemon runs on the laptop, so schedules/sensor are inert while it is down.
At daily/monthly cadence, idempotent sweeps and state-derived predicates make
missed ticks harmless: the next evaluation converges to the same result.

## 8. Dependencies

- `dagster`, `dagster-webserver`, and `dagster-dbt` are already in
  `pyproject.toml`.

No new Terraform, no new IAM: Dagster runs dbt as the same impersonated
`dbt-runner` SA via the existing profile, and the upload asset uses the
existing bucket credentials.

## 9. Testing strategy

- **Pure predicates** (`convergence.py`): unit tests with tmp-dir fixtures
  and injected relation metadata; strict manifest reading uses fake GCS blobs.
- **Invalidation protocol**: request guards/durability, executor interruption
  points, tombstone corruption, and discovery isolation on tmp-dir fixtures.
- **Real local lock**: multiprocessing tests for writer/writer exclusion,
  non-blocking sensor reads, and reader/writer exclusion.
- **Asset wrappers**: thin by design; one test each that the wrapper calls
  its runner with config-derived arguments under the exclusive lock and
  surfaces the pinned metadata semantics.
- **Sensor**: every trigger/skip path, stable upload-derived run keys, bounded
  retry tag, and lock contention.
- **Startup**: tracked retry config loaded through a temporary instance, helper
  unit tests, and a temporary clean-checkout subprocess proving import prepares
  a prod manifest outside `dagster dev`.
- **Definitions smoke test**: all assets, jobs, default-running automations,
  resources, and dbt lineage resolve.
- No integration test drives the real daemon; the daily/monthly behavior is
  the composition of already-tested idempotent sweeps.

## 10. Documentation changes

- **ARCHITECTURE.md** (edit when prompted, per AGENTS.md): the automation
  boundary line changes from "automation is scoped to the cloud side only;
  local assets are materialized manually" to: *the full backfill is manual;
  the incremental current-year refresh and the warehouse rebuild are
  automated (daily sweep + monthly invalidation + staleness sensor). The
  rationale stands — the credit-limited full pull stays a human decision; the
  cheap, bounded refresh does not need one.*
- **STATE.md**: updated at implementation milestones as usual.

## 11. Out of scope / deferred

- **Partition-scoped dbt rebuilds** — rejected (2026-07-08): incremental
  `insert_overwrite` plus the cross-partition dedup DELETE (duplicate ids
  span year shards; prod found 36) is real complexity to save fractions of a
  free-tier dollar. Full rebuild stands.
- **Refresh scope beyond the current year** — Q2/Q3 freshness would require
  re-extracting the 2012–2016 cohort shards (their `counts_by_year` keep
  growing at the source); at ~2.7 M records that is a two-day refresh. Wanted
  eventually (alongside extending Gini coverage toward the current year), but
  a gold-methodology change first; the refresh-target knob here simply gains
  years when that lands.
- **Cloud-hosted Dagster / always-on daemon** — the laptop daemon is
  accepted; revisit only if missed ticks ever matter.
- **Year rollover automation** — bumping the corpus bound in January stays
  manual config.
