# Extraction Module — Design

This document is the consolidated output of the design phase for the extraction module. It pins the decisions, invariants, and high-level structure that the implementation must satisfy. Concrete function signatures, type hints, and docstrings are produced in the contracts step that follows; this document is the policy-and-shape layer.

## Purpose

Extract OpenAlex `works` records for the Computer Science field and land them as raw JSONL page files on local disk. This is the bronze-ingest stage. Downstream Polars → Parquet → GCS is out of scope for this module.

## Scope

In scope:

- Fetch pages from `/works` via cursor pagination.
- Write each page as JSONL to local disk.
- Persist a single cursor per in-progress year for resumption.
- Reconcile record counts per year (drift detection at resume, total reconciliation at completion).
- Handle rate limits, credit exhaustion, and transient errors with appropriate semantics for each.
- Resume cleanly across invocations with no flags or manual state management.

Out of scope:

- GCS upload.
- Parquet conversion or any schema enforcement beyond what OpenAlex returns.
- Other OpenAlex entities (authors, sources, institutions, topics).
- Incremental re-pulls or change-data-capture.
- Parallelism across years. Sequential processing is sufficient — the OpenAlex daily credit budget is the bottleneck, not wall time.

## Operational Model

The module is an **idempotent, resumable job** invoked daily until the full CS corpus is on disk.

- On startup: scan the output tree, determine the resume target year and page, resume from that point.
- On HTTP 429 (assumed daily credits exhausted, based on current EDA): stop cleanly, log final state, exit 0. Expected outcome, not an error.
- On HTTP 403 (assumed sub-second burst rate limit, based on current EDA): exponential backoff, retry up to `MAX_RETRIES`. Treated as transient.
- On HTTP 5xx, timeout, connection reset: exponential backoff, retry up to `MAX_RETRIES`.
- On HTTP 4xx other than 403/429: fail loudly. Likely a configuration bug.
- On count drift detected at resume (see invariants): discard the affected year directory and restart that year cleanly within the same run.
- On count reconciliation failure at year completion: fail loudly, no `_SUCCESS` marker written, manual intervention required.
- On re-run after any clean stop: no flags needed. "Do what's left" is the default behavior.

Year processing order is ascending over a structured year range setting. By default this is 1950 up to `datetime.now().year`, evaluated per invocation. The current year is treated like any other completed snapshot: once `_SUCCESS` exists, the module skips it. A later refresh of the current year is an explicit operator action, such as deleting that year directory or marker. Pre-1950 CS publications are scarce and treated as out of scope by the default year range.

## Data Layout

```
data/raw/works/
  year=1980/
    page_00001.jsonl
    page_00002.jsonl
    ...
    _META.json           # written once on first successful page; immutable thereafter
    _CURSOR              # next-page cursor; absent iff year is complete
    _SUCCESS             # present iff count reconciliation passed at year completion
  year=1981/
    ...
```

- One directory per `publication_year`.
- Pagination is per-year (one cursor walk per year), not global. Year is a natural shard, aligns with the BigQuery partitioning downstream, and bounds the impact of any single failure.
- Each page is a JSONL file containing up to 200 records. A valid zero-result year writes an empty `page_00001.jsonl` so M2 remains true.
- `_META.json` contents (minimal):

  ```json
  {
    "filter": "primary_topic.field.id:17,publication_year:1980",
    "expected_count": 2847,
    "started_at": "2026-04-26T14:23:11Z"
  }
  ```

  Written once, on the first successful page fetch of a year, from the API's first response. Never updated thereafter.

- `_CURSOR` contains the cursor string for the *next* page to fetch. Overwritten atomically after each successful page write. Deleted on the final page of a year.
- `_SUCCESS` is an empty marker file written only after total count reconciliation passes.

Three states a year directory can be in:

- **Untouched**: directory does not exist or is empty.
- **In progress**: `_META.json` and `_CURSOR` present, no `_SUCCESS`.
- **Complete**: `_META.json`, at least one page file, and `_SUCCESS` present.

## Invariants

Each invariant exists to prevent a specific failure mode. The naming convention is `Mn` for stable reference in tests and code comments.

**M1 — Atomic writes.** All file writes use the `tmp → rename` pattern. A reader (including the scan logic on the next invocation) will never see a partially-written file. `fsync` is omitted as a deliberate trade-off: the discipline protects against process crashes (common) but not power loss (rare, recoverable by re-running).

**M2 — `_META.json` ⟺ first page.** `_META.json` exists if and only if at least one page file exists in the year directory. Violation indicates a crash mid-first-page; recovery is to delete the orphan(s) and restart the year.

**M3 — `_CURSOR` ⟺ in progress.** For a year that is in progress (has `_META.json`, no `_SUCCESS`), `_CURSOR` must exist and contain a non-empty cursor for the next page. Missing `_CURSOR` in an in-progress year requires full restart of that year (the cursor cannot be recovered any other way). An empty `_CURSOR` is the same class of recoverable crash state, but is reported with a distinct reason (`empty_cursor`) so logs/tests can distinguish existence from content. For completed years, `_CURSOR` may or may not be present; it is not consulted.

**M4 — Page numbering contiguity.** Page files in a year are numbered contiguously from `page_00001.jsonl`. Gaps indicate manual tampering or filesystem corruption; the affected year is treated as corrupted and surfaces an error.

**M5 — Cursor staleness bound.** `_CURSOR` may be stale by at most one page (cursor pointing to the most recently written page rather than the one after). This is the expected state after a crash between page write and cursor write. On resuming an in-progress year, the runner fetches the page indicated by `_CURSOR`, compares the ordered work IDs in that fetched page to the ordered work IDs in the last page file already on disk, and if they match treats the cursor as stale-by-one. In that case it overwrites the last page file instead of appending a new page. If the ordered IDs do not match, the fetched page is appended as the next page. Staleness by more than one is not recoverable by cursor inspection and will surface through reconciliation or a later invariant violation.

**M6 — Drift detection (primary).** On resuming an in-progress year, the first response's `meta.count` is checked against `_META.json.expected_count`. Mismatch indicates the underlying dataset has shifted and the cursor has become stale; recovery is to discard the year directory contents and restart with a fresh `cursor=*`, within the same run.

**M7 — Count reconciliation (secondary).** At year completion, the sum of records across all page files must equal `_META.json.expected_count`. Mismatch — which can only occur from drift *within* a single contiguous run — fails loudly, blocks `_SUCCESS`, and requires manual intervention.

**M8 — Filter scope consistency.** Any year directory with `_SUCCESS` must have `_META.json.filter` matching the current run's effective per-year API filter, including the year predicate (for example, `primary_topic.field.id:17,publication_year:1980`). If `_SUCCESS` exists but `_META.json` is missing, the year is corrupted: it cannot pass filter validation and must not be treated as complete. The scan step validates completed years as it walks the range; the runner relies on `scan()`'s `completed_years` set when recording skipped years. Mismatch is a loud failure (refusal to mix data from different filter scopes).

**M9 — Snapshot stamp.** Each record, at write time, gets an `_extracted_at` field (ISO 8601 UTC timestamp) injected into the JSON before serialization. This is the per-record snapshot column. The API's `updated_date` field is included in the select list but serves a distinct purpose (record version, not fetch time).

**M10 — Field selection is fixed.** The set of fields requested via OpenAlex's `select` parameter is defined as a single module-level constant (`SELECT_FIELDS`) imported by both the URL builder and any downstream schema code. Changes to this set are deliberate schema changes, not configuration knobs.

## Module Structure

The module is organized as a set of files containing module-level functions, plus value types (frozen dataclasses) and one configuration class (`Settings`, structurally required by pydantic-settings). No classes are introduced for the operational units — each was evaluated against three criteria (cross-method state, multiple instances, multiple implementations) and none met them. See § Design Notes below for the reasoning.

```
src/openalex_pipeline/extraction/
  __init__.py
  __main__.py          # `python -m openalex_pipeline.extraction` -> main() -> run(Settings())
  config.py            # Settings
  constants.py         # SELECT_FIELDS, DEFAULT_FILTER, YEAR_FLOOR, OPENALEX_BASE_URL
  errors.py            # exception hierarchy
  types.py             # Page, YearMeta, ResumeTarget, RecoverableYearState, ResumePlan, YearOutcome, RunSummary
  http.py              # request_page()
  storage.py           # initialize_year, write_page, read_page_work_ids, finalize_year, discard_year
  scan.py              # scan()
  runner.py            # run(), _process_year()
```

### Roles

- **config.py — Settings.** pydantic-settings config object loaded once from environment. Pure data; no methods beyond validation and `resolved_year_range()`.
- **constants.py.** Module-level constants enforcing M10 and pinning operational defaults.
- **errors.py.** Exception hierarchy. See § Error Taxonomy.
- **types.py.** Frozen dataclasses for values passed between functions: `Page`, `YearMeta`, `ResumeTarget`, `RecoverableYearState`, `ResumePlan`, `YearOutcome`, `RunSummary`.
- **http.py — `request_page()`.** Issues one HTTP GET for a given filter + cursor, parses the response, returns a `Page` or raises a typed exception. Owns the retry loop for transient failures (403, 5xx, timeout). Knows nothing about cursors, pages, years, or files beyond passing them through. The HTTP wire is the test seam (mocked via `responses` library), not the Python boundary.
- **storage.py.** All filesystem mutation lives here. Functions: `initialize_year(settings, year, meta)`, `write_page(settings, year, page_number, records, next_cursor, overwrite=False)`, `read_page_work_ids(settings, year, page_number)`, `finalize_year(settings, year)`, `discard_year(settings, year)`. Concentrates M1, M2, M3, M5, M7, M9.
- **scan.py — `scan()`.** Walks year directories ascending, validates each completed year's filter (M8), returns a `ResumePlan`. Performs no writes. Recoverable crash states are reported through `ResumePlan.recovery`; fatal corruption still raises.
- **runner.py — `run()`, `_process_year()`.** `run()` is the public entry point: calls `scan()`, handles any `ResumePlan.recovery` by discarding the affected year before processing, then iterates the configured year range from the beginning. Years reported in `ResumePlan.completed_years` are emitted as `skipped_complete` outcomes and not reprocessed; the first non-complete year is processed from `ResumePlan.target`; later non-complete years are fresh starts. `run()` handles `CreditsExhausted` as a clean stop and handles `DriftDetected` as a single-attempt year restart. `_process_year()` encapsulates one year's worth of work (drift check on first response, stale-cursor page comparison, cursor walk, finalization). The Mn invariants enforced at the loop level: M5 (stale-cursor recovery), M6 (drift check), and honoring M8 through the completed-years plan returned by `scan()`.

## Error Taxonomy

The HTTP layer raises typed exceptions. The runner decides what to do about each. There is no central error handler; errors travel through the normal call stack as values.

| Signal | Origin | Runner policy |
|---|---|---|
| `CreditsExhausted` | HTTP 429 | Stop cleanly, log, return summary with `stopped_reason="credits_exhausted"`. |
| `RateLimited` | HTTP 403 | Exponential backoff in `request_page`; only escapes after retries exhausted, then propagates as fatal. |
| `ServerError` | HTTP 5xx | Same as `RateLimited`. |
| `TransientError` | Timeout, connection reset | Same as `RateLimited`. |
| `BadRequest` | HTTP 400 | Propagate. Configuration bug, fail loudly. |
| `DriftDetected` | M6 mismatch on resume | Caught by runner; discard year directory, restart year once within the same run. Second drift on the same year propagates as fatal. |
| `ReconciliationFailed` | M7 mismatch at year end | Propagate. Loud failure, no `_SUCCESS`. |
| `FilterScopeMismatch` | M8 mismatch | Propagate. Loud failure. |
| `CorruptedYearState` | M4 or other unrecoverable state | Propagate. |
| `RecoverableYearState` | M2/M3 recoverable crash state | Returned by `scan()` inside `ResumePlan`; runner calls `discard_year()` and restarts that year. Stable reason codes include `orphan_meta`, `orphan_pages`, `missing_cursor`, and `empty_cursor`. |

`request_page` never returns `None` or any sentinel value. It either returns a valid `Page` or raises. `Page.records` may be an empty list only for a valid zero-result response with `meta.count == 0` and no next cursor. This is a structural defense against the silent-skip failure mode that plagued the official CLI tool.

## Configuration Surface

All configuration via environment variables, loaded once into a `Settings` object. No CLI flags beyond a thin entrypoint.

| Variable | Purpose | Default |
|---|---|---|
| `OPENALEX_API_KEY` | Required. Authenticates requests. | — |
| `OPENALEX_OUTPUT_DIR` | Root of output tree. | `data/raw/works` |
| `OPENALEX_FILTER` | Override default filter. Dev/test use only. | `primary_topic.field.id:17` |
| `OPENALEX_YEAR_RANGE` | Override year range. Dev/test use only. Format: `1980-2025` or `2024`. | `1950-{current_year}` |
| `OPENALEX_PER_PAGE` | Page size. | 200 |
| `OPENALEX_MAX_RETRIES` | Retries on transient errors (403, 5xx, timeout). | 5 |
| `OPENALEX_LOG_LEVEL` | loguru level. | `INFO` |

Development sampling is achieved by overriding `OPENALEX_FILTER` and/or `OPENALEX_YEAR_RANGE`, not by introducing a separate code path. The runner combines the base filter and each year into an effective per-year API filter by appending `publication_year:{year}`. That effective filter is what gets written to `_META.json`.

## Observability

- Structured logs via loguru: year, page number, records fetched, cumulative progress, cursor preview.
- At end of run: per-year summary line (pages fetched, records fetched, status: `complete` / `in_progress` / `drifted_restarted` / `skipped`).
- `_META.json` and the directory contents themselves serve as machine-readable progress state. No separate progress file.

## Non-Goals (Explicit)

- **No abstract OpenAlex client for arbitrary entities.** Works only.
- **No in-process parallelism.** One cursor walk at a time.
- **No caching layer.** OpenAlex is the source of truth per run.
- **No pluggable storage backend.** Local disk only.
- **No schema validation of returned records.** Trust the API; validate downstream in dbt staging.
- **No defense against dataset drift across long resume gaps beyond M6.** Detection is automatic; recovery is automatic restart of the affected year. The credit budget (~2M records/day) exceeds the largest year (~1.5M), so any drifted year can be refetched within a single quota window — the drift exposure window is bounded by one year's fetch duration, not by total elapsed time.
- **No defense against user tampering with the output directory.** Manual deletion of files mid-run produces undefined behavior. The user owns the directory.
- **No concurrent runs against the same directory.** No lockfile. The user is responsible.

## Design Notes

### Why no classes for the operational units

Each candidate unit (HTTPClient, Scanner, PageWriter, Runner) was evaluated against three criteria for class-hood in Python:

1. Non-trivial mutable state coordinated across multiple methods.
2. Multiple instances at runtime with different state.
3. Multiple implementations behind an interface, where the interface is internal rather than at a mockable external boundary.

None of the units met any of the three criteria:

- **HTTPClient**: state was just a `requests.Session` (one piece, handleable at module level); single instance per run; test seam is the HTTP wire (via `responses` library), not a Python protocol.
- **Scanner**: no state, single invocation per run, single implementation.
- **PageWriter**: no real state — the filesystem owns the state, the writer is just a set of operations on it; single instance; single implementation, with `tmp_path` providing the test seam.
- **Runner**: only one public method (`run`), so its "state" is local variables; single instance; single implementation.

When a class doesn't meet any of these criteria, it's costume rather than substance — it adds ceremony (constructors, `self`, dependency wiring) without buying anything. The classless version makes state more honest (it lives in the filesystem and in pydantic-settings) and removes the need for explicit dependency injection.

Trade-offs accepted: no constructor-injected dependency declarations (mild loss of self-documentation); no structural type for "an HTTP client" (irrelevant since we test at the wire); divergence from default Python OOP idioms (minor cognitive cost for readers).

If during implementation any unit acquires genuine cross-method state (e.g., a request-rate-limiter that remembers when the last request was), it should be promoted to a class at that point. The decision is per-unit, not architectural.

### Why errors travel as exceptions, not return values

The official CLI tool's silent-skip bug — where 429 responses were logged as errors but recorded as successes in the checkpoint file — was caused by a function returning `None` (or similar) on failure, which the caller couldn't distinguish from success. The structural fix is to make the failure path a different *type* of return, not a different value. Python's exception mechanism provides this: a function either returns a valid result or raises. There is no third state to misinterpret.

This is why `request_page` is documented as "never returns None" — it's not a comment, it's a contract that the test suite verifies. Empty records are valid only for a real zero-result API response.

### Why `_META.json` is write-once

`_META.json` records a target (`expected_count`), not progress. Targets don't change during a run. The progress *is* the page files on disk. Decoupling target from progress means there's no opportunity for the two to disagree — a class of bug the old CLI's checkpoint file was susceptible to.

## What This Document Does Not Cover

- Function signatures, type hints, docstrings — produced in the next step (contracts).
- Test cases — produced after contracts, before implementation.
- Specific retry timings, backoff curves — implementation concern, defaults are fine.
- Private helper functions — included in contracts only where they encode a non-obvious design decision (e.g., atomic-write helper for M1); excluded where they're pure refactoring of obvious logic.
