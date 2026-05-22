# Extraction Module — Design & Invariants

Settled decisions for the OpenAlex `works` extraction module. Input for step 2
(pinning internal API contracts). Treat invariants as binding; everything else
is rationale.

## Scope

Extract OpenAlex `works` for the CS field, land verbatim as JSONL (one file per
API page) on local disk. Raw extraction only — no transformation. Idempotent,
resumable, manually invoked once per day until the full subset is on disk.
Downstream (Polars → Parquet → GCS → BigQuery) is out of scope.

Guiding principles: **simplicity and specificity**. This is a pipeline-specific
module, not a general extraction tool. Cheap abstractions with no downside are
fine; speculative generality is not.

## Operational Model

- **Invocation**: manual CLI, ~once/day. No cron/Dagster yet; the core raises
  typed exceptions so an orchestrator can wrap it later without refactor.
- **Shard unit**: one calendar year. Run = constant query + year range. Each
  year is paginated independently with `cursor=*`.
- **Sequential**. The OpenAlex daily credit budget (~2 M records) is the
  bottleneck, not wall time. Largest year (~1.5 M) fits one day's budget, so a
  year started fresh always completes in one run.
- **Free credit tier**. Per-year sharding leaves process parallelism as an
  unused escape hatch.

## Module Structure

Five subunits. Only `Settings` holds module state; all other state lives on
disk — **the filesystem is the source of truth**.

| Unit | Form | Responsibility |
|---|---|---|
| `Settings` | Pydantic `BaseSettings` | Config from env vars only. Key params (API key, query params) required. |
| runner | `run()` | Builds query, loops years, classifies each, invokes worker for non-complete years, aggregates run report. |
| worker | `process_year()` | Paginates one year shard. State machine. Where the real work is. |
| connector | `fetch_page()` | The single API call + retry/backoff. Primary test seam, injected as a closure. |
| storage | `storage.py` | All filesystem I/O. Exposes verb functions to the worker + state classification to both worker and runner. |

## On-Disk Layout

```
{root}/{year}/
  _META.json          # immutable; written first for a fresh year
  _CURSOR.json         # mutable; resume pointer
  page-0001.jsonl      # one file per API page, 200 records each (fewer only in tests)
  page-0002.jsonl
  ...
  _YEAR_REPORT.json    # written last; its existence = year complete
```

No `_SUCCESS` marker. A valid `_YEAR_REPORT.json` with non-null `completed_at`
is the authoritative completion signal.

## Year State Machine

Exactly three valid states. Classification is a **pure function in `storage`**,
used by the runner (skip-vs-invoke) and by the worker (first step). Single
source of truth.

| State | Disk condition |
|---|---|
| **fresh** | Directory missing or empty |
| **in progress** | `_META.json` + `_CURSOR.json` + ≥1 page file; no `_YEAR_REPORT.json` |
| **complete** | in-progress files + valid `_YEAR_REPORT.json` |

Any other combination → **corrupted → loud failure** raised by `storage`.

Query-match (`_META.query` == current run's query) is checked separately for
any non-fresh year; mismatch is a loud failure (see Invariant 4). A year is
"complete *for this run*" only if both complete **and** query-matched.

## Resume Algorithm (the core idea)

`_CURSOR.json` is written **before any page file** for a fresh year and always
holds the cursor for the *next* page to write. Therefore:

1. Worker classifies state. Fresh → write `_META.json`, then `_CURSOR.json` as
   `{cursor: "*", next_page: 1}`.
2. Read `_CURSOR.json` → `(C, N)`.
3. Fetch with `C`. Write `page-{N}` atomically (**always overwrite**).
4. Write `_CURSOR.json` atomically as `(C', N+1)`.
5. Repeat until fetched cursor is `null` → write `_YEAR_REPORT.json`.

**Idempotent by construction.** The cursor in the file is always the one for
`next_page`, so the worker unconditionally overwrites `page-{next_page}`. A
crash between steps 3 and 4 costs exactly one re-fetched page on resume — no
staleness check, no special-casing. `next_page` is the resume pointer, not a
diagnostic.

OpenAlex cursor mechanics: fresh year initializes `cursor="*"`; `null` signals
all pages fetched.

## Invariants

1. **Query isolation.** `_META.json` records the full query (minus
   `https://api.openalex.org/`). For any non-fresh year, `_META.query` must
   match the current run's query exactly. Mismatch → loud failure. Mixing
   queries corrupts data.

2. **`_META.json` is immutable** once written, and written before the first
   page file.

3. **Write order per page is fixed**: fetch → write `page-N` → update
   `_CURSOR.json`. Enforced in code. This is what makes resume idempotent.

4. **Atomic writes**: tmp + flush + rename for every file. No `fsync` (too slow
   for the benefit at this scale).

5. **`_YEAR_REPORT.json` is immutable** once written; its presence (with
   non-null `completed_at`) means complete.

6. **Corruption is loud.** The module manages only the files above. It does not
   guard against external tampering, but any classification ambiguity or
   blatant inconsistency → loud failure from `storage`. No silent recovery.

## Count Check (sanity only)

`_META.json` stores `meta.count` from the first page's response as
`expected_count`. On year completion the worker counts lines across all page
files and compares.

- **Non-blocking.** A mismatch never blocks completion. Data consolidation is
  out of scope.
- Result recorded in `_YEAR_REPORT.json` (`expected_count`, `records_fetched`,
  and a `count_mismatch` warning field). Surfaced in the run report.
- **This is a smoke alarm, not a guarantee.** It catches *net* count change,
  not *churn* — a concurrent add + delete leaves the count matching while the
  data is still inconsistent. The real defense against drift is that a year
  usually completes within one day, keeping the drift window small.

Checked **in the worker**, at the moment of writing `_YEAR_REPORT.json` — the
only unit that knows when a year transitions to complete. The runner only
*aggregates* reports; it never computes counts, which keeps the report step
crash-trivial.

## Run Report

Built fresh each invocation by the runner: scan year directories, classify
each, read each `_YEAR_REPORT.json`. Pure aggregation, no computation, no disk
writes. Reports per-year status (complete / in progress / fresh / pending) and
surfaces count-mismatch warnings.

Skipped (already-complete, query-matched) years: a runtime log line + a
`complete` entry in the run report. **Nothing written to disk for a skip.** The
worker is invoked only for fresh / in-progress years. No re-verification of
complete years — re-reading every page file of every done year on each run
gets expensive once most years are done.

## Error Handling

Connector raises only at fetch time — no in-flight on-disk state to clean up.
429 is always caught *between* pages, never mid-page-write (guaranteed by the
fixed write order).

| HTTP | Mode |
|---|---|
| `200` | Success |
| `301` | Loud failure (entity merged; should not occur for list queries) |
| `403` | Exponential backoff + retry to `MAX_RETRIES`, then raise. Subsecond-burst rate limit; not expected with `requests` (sync). |
| `400`, `404`, other `4xx` | Loud failure |
| `429` | **Clean stop.** Daily free-credit exhaustion — expected once/day. Connector raises a typed `DailyLimitReached`; worker and runner let it propagate; caught only in `__main__`. Resume next day. |
| `5xx` | Exponential backoff + retry to `MAX_RETRIES`, then raise. |

Worker propagates `DailyLimitReached` *after* `_CURSOR.json` is consistent —
the fixed write order guarantees this already.

## Connector Contract (preview for step 2)

`fetch_page` is injected into `process_year` as a closure. Retry/backoff lives
*inside* the real closure; the worker sees only clean returns or a typed raise.
Preliminary signature, to be pinned in step 2:

```
fetch_page(url: str) -> (records: list, next_cursor: str | None, meta_count: int)
```

This is the highest-leverage contract in the module.

## Sequencing

Vertical slice first — worker + storage + connector, where the risk lives. The
runner is a trivial loop; `Settings` is boilerplate.

1. Pin worker state machine + on-disk layout invariants. *(done — this doc)*
2. Pin three contracts: `fetch_page` signature, the `storage` function set, the
   `_CURSOR.json` / `_META.json` / `_YEAR_REPORT.json` schemas.
3. Tests for `process_year` against a fake `fetch_page` closure + tmp
   filesystem. ~80% of test value.
4. Implement against the tests.
5. Runner + `Settings` as a trivial second pass.

## Open Items for Step 2

- Exact JSON schemas for `_META.json`, `_CURSOR.json`, `_YEAR_REPORT.json`.
- Final `fetch_page` signature — does it take a URL, or `(query, cursor)`?
- The full `storage` function set and their exact signatures.
- Typed exception hierarchy (`DailyLimitReached`, corruption, query mismatch,
  retry-exhausted).