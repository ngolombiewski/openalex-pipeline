# Orchestration Implementation Review

*Reviewed: 2026-07-15. Findings recorded: 2026-07-17.*

## Scope

Review of the uncommitted Dagster orchestration stage against the project
architecture, `docs/orchestration-design.md`, existing runner contracts, and
the project principles in `AGENTS.md`.

The reviewed stage adds:

- Dagster assets for extraction, bronze, upload, and dbt.
- Daily local sweep and monthly current-year invalidation schedules.
- A warehouse staleness sensor and cloud metadata helpers.
- A guarded `invalidate_year` pipeline operation.
- Orchestration tests and corresponding documentation changes.

## Findings

### 1. High: failed warehouse builds will not retry

`warehouse_staleness_sensor` uses a stable upload-timestamp `run_key` in
`src/openalex_pipeline/orchestration/definitions.py`. Dagster permits only one
run per sensor run key across all evaluations. After a failed build, subsequent
stale evaluations therefore produce the same deduplicated request.

This contradicts the self-healing behavior specified in
`docs/orchestration-design.md`: a partial warehouse build remains stale, but the
sensor will not launch the promised retry until a later upload changes the key.

Recommended resolution: return a `RunRequest` without a run key and rely on the
existing in-progress guard plus the four-hour minimum interval. Add a test that
models repeated stale evaluations after a failed run.

### 2. High: invalidation is not interruption-safe

`invalidate_year` deletes the extraction directory before deleting the bronze
parquet. An interruption between those operations leaves the old parquet in
place. Once extraction completes again, bronze checks parquet presence first
and classifies the year as already ingested. Convergence can then accept the old
local parquet and old GCS object.

This was reproduced locally: after constructing a new complete extraction
beside the old parquet, bronze reported `ingested` and orchestration reported
`converged=True`.

The behavior contradicts the design claim that partial deletion is always loud
or resumable. A durable filesystem invalidation marker, tombstone, or equivalent
recovery protocol is needed. Reversing deletion order alone prevents this exact
stale-parquet state but can still silently skip the intended refresh after an
interruption.

### 3. High: definitions depend on an ignored dbt artifact

The `@dbt_assets` decorator reads `dbt/target/manifest.json` during module
import, while `dbt/.gitignore` excludes `target/`. A clean checkout therefore
cannot load the Dagster definitions. Local validation succeeds only because a
previously generated manifest is present in the working tree.

Recommended resolution:

- Development: call `DBT_PROJECT.prepare_if_dev()` before the decorator.
- Daemon/deployment: add an explicit manifest preparation and packaging step.
- Ensure the prepared manifest uses the intended prod configuration.

### 4. High: the documented `DAGSTER_HOME` is invalid

`.env.example` sets `DAGSTER_HOME=.dagster`. Dagster requires this value to be
an absolute path naming an existing directory. The real `.env` did not contain
the setting during review, so definitions validation used temporary state and
did not exercise persistent instance initialization.

Recommended resolution: establish an explicit environment bootstrap contract.
For example, `.envrc` could derive an absolute in-repo path and create the
directory before exporting it. The directory is now gitignored.

### 5. Medium: a missing or malformed upload manifest means "warehouse fresh"

`upload_manifest_uploaded_at` returns an empty list when the manifest is absent
or lacks `uploaded_at`. `warehouse_is_stale` converts an empty list to `False`.
The sensor consequently reports a fresh warehouse even though it cannot
establish an authoritative input timestamp.

This conflicts with both "corruption is loud" and the bootstrap promise that
the first converged corpus triggers a warehouse build.

Recommended resolution: make a missing manifest non-converged, and raise a
typed corruption exception for a present manifest with an invalid pinned
schema. Do not silently map either case to freshness.

### 6. Medium: automation ships disabled without an activation contract

Both schedules and the sensor use Dagster's default `STOPPED` status. This may
be the correct safety policy, particularly for destructive invalidation, but
the README and design describe the refresh as automated without documenting
initial activation or daemon operation.

Recommended resolution: decide whether definitions should default to running
or require deliberate activation, then document the exact startup and
activation procedure.

### 7. Medium: the specified wrapper and sensor tests are missing

The design promises tests for each asset wrapper and for resolved sensor
wiring. The implementation contains pure convergence and invalidation tests,
but `tests/orchestration/test_definitions.py` only validates that `Definitions`
loads.

Missing coverage includes:

- Runner arguments and asset metadata.
- Sensor convergence, freshness, in-progress, and retry paths.
- Cloud manifest absence and corruption.
- Clean-checkout dbt manifest preparation.
- Schedule and sensor activation policy.

These omissions allowed the retry and startup defects above to pass the suite.

### 8. Low: asset metadata overstates work performed

The extraction asset sums persisted `records_fetched` values for skipped years,
so a no-op sweep appears to fetch the full corpus again. The bronze runner
returns a final-state manifest that cannot distinguish newly ingested years from
skipped years. Upload `bytes` includes skipped objects rather than only bytes
transferred during the run.

The design's per-run metadata contract is not fully achievable from the current
runner return types while preserving thin wrappers. Either rename the values as
state totals, omit unavailable metrics, or explicitly extend runner contracts.

## Design Assessment

The core shape is sound:

- The end-to-end asset graph resolves correctly, including
  `bronze_gcs -> stg_works`.
- Existing runners remain authoritative for skip, resume, and failure behavior.
- Prod dbt targeting is explicit.
- Canonical query identity is checked during convergence.
- Minimum modification time across every dbt model correctly protects against
  partial warehouse rebuilds.
- The existing GCS shard remains available while a local refresh is in flight.

The pooled AI-vs-rest limitation in the gold layer is also valid: subfield
medians and Ginis do not compose into pooled metrics. Documentation was amended
so the current outputs are described as subfield comparisons only.

## Minor Fixes Applied During Review

- Added `.dagster/` to the root `.gitignore`.
- Replaced BigQuery exception class-name inspection with typed
  `google.api_core.exceptions.NotFound` handling.
- Removed new orchestration Pyright errors.
- Formatted all new orchestration source and test files.
- Corrected stale README and architecture references to orchestration as
  "next" or "later".
- Corrected the gold design and README so exploratory subfield comparisons are
  not presented as pooled AI-vs-rest statistics.
- Removed the gold design's stale assumption that annual AI share must be
  monotonic.
- Updated the `STATE.md` review timestamp.

## Verification Snapshot

- `uv run pytest`: 174 passed.
- `uv run ruff check .`: passed.
- `uv run ruff format --check src/openalex_pipeline/orchestration tests/orchestration`:
  passed.
- `uv run pyright src/openalex_pipeline/orchestration tests/orchestration`:
  passed.
- Dagster definitions validation: passed with the existing local dbt manifest
  and temporary Dagster instance state.
- `git diff --check`: passed.

Repository-wide checks still contain pre-existing debt outside this stage:

- `uv run pyright`: six errors in scripts and an existing bronze test.
- `uv run ruff format --check .`: 20 existing files would be reformatted.

## Review Gate

Resolve findings 1 through 5 and decide the activation policy in finding 6
before committing the orchestration stage. Add the missing behavioral tests
before implementing those resolutions, following the project's contracts,
tests, implementation workflow.
