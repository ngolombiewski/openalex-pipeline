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
| `extracted_jsonl` | `extraction.runner.run(Settings())` | `status` (`complete` / `stopped_daily_limit`), years processed, records fetched |
| `bronze_parquet` | `bronze.runner.run(extract_root, bronze_root, years)` | years ingested vs skipped, manifest row count |
| `bronze_gcs` | `upload.runner.run(bronze_root, bucket)` | years uploaded vs skipped, bytes |

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

The dbt models become assets via **`dagster-dbt`** (`@dbt_assets` over the
project's manifest), which surfaces every model and test with real lineage.
The dbt source `bronze_external` is mapped to the `bronze_gcs` asset key so
the graph is connected end to end:

```
extracted_jsonl → bronze_parquet → bronze_gcs → stg_works → silver_works → gold_*
```

**Dagster only ever runs dbt with `-t prod`.** The dev target remains the
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

An op job (it destroys state; it is an operation, not an asset) that calls the
new `invalidate_year` capability (§6) on the refresh target. Scheduled
**monthly**. The refresh target is `Settings().end_year` — the same pin as the
corpus bound. (Year rollover — bumping `OPENALEX_END_YEAR` and the dbt
corpus-bounds vars in January — remains the manual config change it already
is; this design does not touch it.)

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
- A failed `warehouse_build` leaves at least one dbt-managed table unrebuilt,
  which keeps the staleness predicate true (§5), so the sensor re-triggers:
  self-healing, and loud (failed runs are visible in the UI) rather than
  silently stale. The sensor skips while a `warehouse_build` run is in
  progress, and its `minimum_interval_seconds` is set high (hours) so a
  persistently failing build produces a handful of visible failures per day,
  not a hot loop.
- Bootstrap gets the right behavior for free: the first converged tick
  triggers the first warehouse build; nothing builds over a partial corpus.

Cost note: a full prod rebuild bills ~43 GiB. The sensor fires roughly once
per monthly refresh, comfortably inside the BigQuery free tier.

## 5. Convergence and staleness predicates

Two pure functions in `orchestration/` (e.g. `convergence.py`), fully
unit-testable, no Dagster imports:

**Converged** — "another sweep would change nothing":

1. Every year in `[start_year, end_year]` has a complete extraction landing
   zone. Read via the extraction storage contract, not path spelunking: the
   predicate constructs `canonical_query(Settings().filter, year)` (public on
   the extraction runner for exactly this kind of caller) and calls
   `classify_year(root, year, query)`, treating COMPLETE as converged. Using
   `classify_year` rather than bare `read_year_report` means convergence also
   asserts query homogeneity — a changed `OPENALEX_FILTER` over stale landing
   zones raises `QueryMismatch` loudly instead of converging over
   wrong-filter data.
2. Every year's bronze parquet exists on disk. (Freshness relative to
   extraction is already asserted loudly by the bronze manifest's
   `records_fetched == bronze_row_count` check — trust the layer below; do
   not re-derive it here.)
3. GCS is closed over local: for every year, the existing
   `upload.core.should_skip(local_mtime, blob_updated)` returns True — blob
   present and at least as new as the local file.

**Warehouse stale** — with memory, so a failed build cannot strand the
warehouse:

```
max(uploaded_at) in the GCS upload manifest
  >  min(last_modified) over ALL dbt-managed tables in the prod dataset
```

Both sides are authoritative system metadata (GCS blob `updated` projected
into the upload manifest; BigQuery table metadata via
`INFORMATION_SCHEMA.TABLES` or the client's `table.modified`). Nothing is
written to remember state; staleness is re-derived on every evaluation.

The `min` must range over **every** model, not a single sentinel: `dbt build`
materializes in dependency order, so a run that dies at silver or gold leaves
the upstream tables fresh — a `stg_works`-only sentinel would flip to
not-stale after a *partial* build and strand the downstream tables (review
finding, 2026-07-09). With min-over-all, any unrebuilt model keeps the
predicate true and the sensor re-triggers. The table list is derived from the
dbt manifest (the same artifact `dagster-dbt` loads), never hardcoded, so new
models are covered automatically. A table absent from the dataset counts as
infinitely stale (bootstrap: first converged tick triggers the first build).

One deliberate nuance: a run that rebuilds every table but fails a *test*
ends not-stale. That is correct — re-running cannot fix a deterministic test
failure; that case needs a human and gets a loud failed run in Dagster.
Transient mid-build failures (the ones re-running can fix) always leave a
table unrebuilt and therefore re-trigger.

The sensor evaluates `converged AND stale`. Evaluation cost per tick: local
stat calls, one GCS manifest read + blob listing, one BigQuery metadata
lookup — cheap enough for an hourly interval.

## 6. New module capability: `invalidate_year`

The only piece that touches module contracts, so it gets the full
contracts → tests → implementation treatment.

**Contract** (proposed home: `orchestration/invalidate.py` — it is a
pipeline-level operation spanning two layers' artifacts; the layout knowledge
it needs is reached through public surfaces, not duplicated):

```
invalidate_year(
  extract_root: Path,
  bronze_root: Path,
  year: int,
  query: str,
) -> InvalidationResult
```

- **Guard:** refuses to touch an *incomplete* year. If the year's landing
  zone is not COMPLETE (no `_YEAR_REPORT.json`), the year is mid-refresh —
  return a no-op result (`skipped_in_progress`) and log it. This is what
  makes re-triggering safe: a monthly tick landing during an in-flight
  multi-day refresh cannot clobber a half-pulled landing zone. A *missing*
  year directory is also a no-op (`skipped_absent`) — already invalidated.
  Any other on-disk shape is the extraction layer's CorruptedState and
  propagates from `classify_year` untouched. The caller supplies the current
  canonical query (`canonical_query(Settings().filter, year)`) so a changed
  filter over stale landing-zone state raises `QueryMismatch` instead of
  deleting the wrong corpus shard.
- **Deletion scope:** the year's extraction directory
  (`{extract_root}/{year}/`) and its bronze parquet
  (`{bronze_root}/{year}.parquet`). **Not** the GCS shard — it keeps serving
  the external table until the refreshed upload overwrites it, and its
  presence-with-older-timestamp is exactly what makes `should_skip` return
  False for the re-upload.
- The bronze manifest is *derived* and rebuilt wholesale on the next bronze
  run; a stale manifest row between invalidation and the next sweep is
  expected and harmless.
- Deletion is `rm -rf` of the year dir; there is no atomicity requirement — a
  partially deleted landing zone classifies as CorruptedState or IN_PROGRESS
  on the next run, both of which are loud or resumable, never silent.

**Tests:** guard behavior (complete → deletes both artifacts; in-progress →
no-op; absent → no-op; corrupted → propagates), deletion scope (GCS untouched
— trivially, it takes no bucket), and result reporting.

## 7. Dagster instance state

`DAGSTER_HOME` points at a gitignored in-repo directory (`.dagster/`), set in
`.env` / `.env.example`. This is the one new state store the project
acquires; per §2 it is explicitly advisory — event log and schedule cursors
only. Deleting it resets history and schedule bookkeeping, nothing else.

The daemon (`dagster dev` during development; `dagster-daemon` + webserver
for "production") runs on the laptop. Honest limitation, stated rather than
hidden: schedules and the sensor only evaluate while the daemon runs. At a
daily/monthly cadence with idempotent sweeps and a stateless staleness
predicate, missed ticks cost nothing — the next evaluation converges to the
same result. This is precisely why the predicates were designed memoryless.

## 8. Dependencies

- `dagster`, `dagster-webserver`, and `dagster-dbt` are already in
  `pyproject.toml`.

No new Terraform, no new IAM: Dagster runs dbt as the same impersonated
`dbt-runner` SA via the existing profile, and the upload asset uses the
existing bucket credentials.

## 9. Testing strategy

- **Pure predicates** (`convergence.py`): unit tests with tmp-dir fixtures
  and injected metadata; no cloud, no Dagster.
- **`invalidate_year`**: contract tests per §6, tmp-dir fixtures.
- **Asset wrappers**: thin by design; one test each that the wrapper calls
  its runner with the right arguments and surfaces the report as metadata
  (runner mocked at the same seam the module tests already use).
- **Definitions smoke test**: the `Definitions` object loads (assets, jobs,
  schedules, sensor resolve) — catches wiring drift, including the dbt
  manifest mapping.
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
