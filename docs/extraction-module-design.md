# Extraction Module — Design & Contracts

Settled design for the OpenAlex `works` extraction module.

## Scope

Extract OpenAlex `works` for the CS field, land raw records as JSONL (one file
per API page) on local disk. Raw extraction only — no per-record transformation.
Idempotent, resumable, manually invoked once per day until the full subset is on
disk. Downstream (Polars → Parquet → GCS → BigQuery) is out of scope.

Bronze-only columns such as `_extracted_at` are added later during the JSONL →
Parquet bronze materialization step, not by this module.

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
| runner | `run()` | Builds canonical query, loops years, invokes worker for every year, aggregates run report. |
| worker | `process_year()` | Paginates one year shard. State machine. Where the real work is. |
| connector | `fetch_page()` | The single API call + retry/backoff. Primary test seam, injected as a closure. |
| storage | `storage.py` | All filesystem I/O. Four public functions; classification logic for the worker. |

## On-Disk Layout

```
{root}/{year}/
  _META.json          # immutable; written first for a fresh year
  _CURSOR.json        # mutable; resume pointer
  page-0001.jsonl     # one file per API page, 200 records max (fewer on last page/tests)
  page-0002.jsonl
  ...
  _YEAR_REPORT.json   # written last; its existence = year complete
```

No `_SUCCESS` marker. The presence of `_YEAR_REPORT.json` is the authoritative
completion signal.

## Year State Machine

Exactly three valid states. Classification is performed by `classify_year` in
`storage` and is the worker's first step. The runner does **not** classify —
it always invokes the worker, which returns immediately for a complete year.

| State | Disk condition |
|---|---|
| **FRESH** | Directory missing or empty |
| **IN_PROGRESS** | `_META.json` + `_CURSOR.json` + ≥1 page file; no `_YEAR_REPORT.json` |
| **COMPLETE** | `_YEAR_REPORT.json` present |

Any other combination → **corrupted → loud failure** (`CorruptedState`).

Query-match is checked by `classify_year` for any non-fresh year; mismatch →
`QueryMismatch`. For FRESH/IN_PROGRESS states, the stored query comes from
`_META.json`. For COMPLETE, the stored query comes from `_YEAR_REPORT.json`, so
completion does not depend on `_CURSOR.json`.

### Finalize-pending sub-state

After the last page, `_CURSOR.json` holds `cursor: null`. A crash here (last
`write_page` done, `finalize_year` not yet) leaves a year that classifies as
**IN_PROGRESS with `cursor = None`**. This is a valid, expected state meaning
"all pages fetched, finalize pending." It is **not** a fourth `YearState` — the
worker infers it from `IN_PROGRESS + cursor is None` and jumps straight to
`finalize_year` without entering the fetch loop.

## Resume Algorithm (the core idea)

`_CURSOR.json` is written **before any page file** for a fresh year and always
holds the cursor for the *next* page to write. `write_page` always overwrites
`page-{next_page}`. Therefore the job is **idempotent by construction**: a crash
between writing a page and updating the cursor costs exactly one re-fetched page
on resume — no staleness check, no special-casing.

`next_page` is the resume pointer, not a diagnostic. State flows disk → memory
exactly once per run (at `classify_year`), then memory → disk repeatedly (each
`write_page`). The worker holds `page_number` as a loop induction variable;
`_CURSOR.json`'s copy exists for the *next* run.

### Worker loop (final form)

```
status = classify_year(root, year, query)

if status.state == COMPLETE:
    return  # skipped outcome, carrying the persisted _YEAR_REPORT fields

if status.state == FRESH:
    records, next_cursor, meta_count = fetch_page(query, cursor="*", api_key=...)
    initialize_year(root, year, query, meta_count)
    write_page(root, year, records, next_cursor, page_number=1)
    cursor, page_number = next_cursor, 2
else:  # IN_PROGRESS
    cursor, page_number = status.cursor, status.next_page

while cursor is not None:
    records, next_cursor, _ = fetch_page(query, cursor=cursor, api_key=...)
    write_page(root, year, records, next_cursor, page_number)
    cursor, page_number = next_cursor, page_number + 1

report = finalize_year(root, year)
return  # completed outcome, carrying report
```

Ordering on the fresh path is pinned: `fetch_page → initialize_year →
write_page`. `initialize_year` needs `meta_count` from the first response, and
this ordering means a `fetch_page` failure leaves nothing on disk to clean up.

OpenAlex cursor mechanics: fresh year initializes `cursor="*"`; the API stops
returning a cursor on the last page, normalized to `None`.

The worker returns an in-memory `YearOutcome` for every handled year. This is an
invocation outcome, not persistent state:

```
@dataclass
class YearOutcome:
    year: int
    status: Literal["completed", "skipped"]
    report: YearReport
```

For a COMPLETE, query-matched year, the worker calls `read_year_report` and
returns a `skipped` outcome. For a year completed during the current invocation,
`finalize_year` writes and returns the report, and the worker returns a
`completed` outcome.

`DailyLimitReached` propagates out of the worker because the current year has no
completed/skipped year outcome. The runner catches it so it can return the
partial run report.

## Storage Contract

Five public functions. **`storage.py` (the stub) is authoritative for exact
signatures**; the forms below omit the leading `root: Path, year: int` that all
five take, as noise. Page-file numbering, atomic writes, and `tmp` files are
internal (`_write_pagefile`, `_write_cursor`, etc.) and not part of the
contract.

```
classify_year(query: str) -> YearStatus
    # Classifies the year directory. For non-fresh years, also checks the
    # stored query (_META.query for IN_PROGRESS, _YEAR_REPORT.query for
    # COMPLETE) against query.
    # Raises: CorruptedState, QueryMismatch

initialize_year(query: str, meta_count: int) -> None
    # Writes _META.json (query, expected_count=meta_count, started_at=now),
    # then _CURSOR.json ("*", 1). started_at generated inside.

write_page(records: list[dict], next_cursor: str | None, page_number: int) -> None
    # Writes page-{page_number}.jsonl, then overwrites _CURSOR.json with
    # (next_cursor, page_number + 1). Write-only: reads nothing.
    # Always writes a page file, even when records is empty (see below).

finalize_year() -> YearReport
    # Reads _META.json, counts lines across all page files, writes
    # _YEAR_REPORT.json, and returns the report. completed_at generated inside.

read_year_report() -> YearReport
    # Reads _YEAR_REPORT.json and returns it. Called by the worker on the
    # COMPLETE skip path to hydrate the YearOutcome.
```

`read_year_report` pairs with `finalize_year` (write/read symmetry). The
COMPLETE path of `classify_year` already opens `_YEAR_REPORT.json` for the
query-mismatch check; reopening it once more in `read_year_report` is a
deliberate trade for keeping `YearStatus` narrow (no `report` field meaningful
only on COMPLETE).

`YearStatus` is a small dataclass (not a bare enum — it must carry the resume
pointer):

```
@dataclass
class YearStatus:
    state: YearState              # FRESH | IN_PROGRESS | COMPLETE
    cursor: str | None = None     # meaningful only if IN_PROGRESS; may be None
    next_page: int | None = None  # meaningful only if IN_PROGRESS
```

`write_page` is **write-only by design**: it is handed `page_number` (the
worker's induction variable) and never reads `_CURSOR.json`. Reads are justified
by need-to-know (`classify_year` hydrates in-memory state once per run); writes
are justified by recoverability. `write_page` needs neither a read nor a
staleness check.

### Empty-page handling

A zero-result year is valid: `fetch_page` returns `([], None, 0)`. `write_page`
does **not** branch on `len(records)` — it writes `page-{n}.jsonl` regardless.
For an empty page that file is **zero bytes** (JSONL of zero records = empty
string, not `[]`, not a blank line). A zero-result year therefore has exactly
one empty `page-0001.jsonl`.

This keeps the invariant "≥1 page file exists for any non-fresh year" true,
which `classify_year` depends on — the empty page file is load-bearing for
classification of a crashed zero-result year.

## Connector Contract

```
fetch_page(query: str, cursor: str, api_key: str)
    -> tuple[list[dict], str | None, int]
    #  (records, next_cursor, meta_count)
```

- `query` — opaque string, the full query minus the `https://api.openalex.org/`
  prefix, minus `cursor`, and minus the API key, exactly as stored in
  `_META.json`. The runner builds this canonical string. The connector treats it
  as opaque; no structured form. Equality of this string is the query-isolation
  invariant.
- `cursor` — passed separately (`"*"` for the first call). Not part of `query`
  in our nomenclature.
- `api_key` — passed separately. A credential, **not** part of query identity;
  it must never be written into `_META.json`.
- The connector assembles the URL: `https://api.openalex.org/{query}&cursor=
  {cursor}` plus the key param. The order in which the connector appends
  `cursor` and API-key parameters is not part of query identity.
- `records` is `list[dict]` — the response `results` array, parsed but
  otherwise untouched. No model, no per-record validation; bronze begins
  downstream. Note this implies a `json.loads` → (`write_page`) `json.dumps`
  round-trip: landed JSONL is verbatim *at record level*, not byte-identical.
- `next_cursor` is `None` when the API returns no further cursor (last page).
- `([], None, 0)` is a valid return (zero-result year).

`fetch_page` is injected into `process_year` as a closure. Retry/backoff lives
*inside* the real closure; the worker sees only clean returns or a typed raise.
The connector raises only at fetch time — no in-flight on-disk state.

## Query Construction

`run()` constructs the canonical query string once per year. That exact string
is stored in `_META.query` and used for query-isolation comparison. It excludes
the host prefix, `cursor`, and API key.

Canonical query shape:

```
works?filter=primary_topic.field.id:17,publication_year:{year}&select={columns}&per_page=200
```

`select` is required and is pinned to the bronze source columns from
`docs/DATA_MODEL.md`:

```
id,title,publication_year,publication_date,type,language,is_retracted,
is_paratext,primary_topic,topics,cited_by_count,counts_by_year,
cited_by_percentile_year,citation_normalized_percentile,fwci,
referenced_works_count,open_access,doi,ids,keywords,updated_date
```

The runner owns parameter order and filter order. The connector may append
`cursor` and the API key in any order because neither is part of query identity.

## JSON Schemas

### `_META.json` — written once by `initialize_year`, immutable

```json
{
  "query": "works?filter=primary_topic.field.id:17,publication_year:2018&select=id,title,publication_year,publication_date,type,language,is_retracted,is_paratext,primary_topic,topics,cited_by_count,counts_by_year,cited_by_percentile_year,citation_normalized_percentile,fwci,referenced_works_count,open_access,doi,ids,keywords,updated_date&per_page=200",
  "expected_count": 148231,
  "started_at": "2026-05-22T09:14:03Z"
}
```

### `_CURSOR.json` — written by `initialize_year`, overwritten by every `write_page`

```json
{ "cursor": "IlsxNjA5NDU5MjAwMDAwLCAn...", "next_page": 7 }
```

- `cursor`: OpenAlex token for `next_page`. Initial value `"*"`. After the last
  page, JSON `null` (the finalize-pending sub-state).
- `next_page`: integer. Initial value `1`.

### `_YEAR_REPORT.json` — written once by `finalize_year`, immutable

```json
{
  "query": "works?filter=primary_topic.field.id:17,publication_year:2018&select=id,title,publication_year,publication_date,type,language,is_retracted,is_paratext,primary_topic,topics,cited_by_count,counts_by_year,cited_by_percentile_year,citation_normalized_percentile,fwci,referenced_works_count,open_access,doi,ids,keywords,updated_date&per_page=200",
  "year": 2018,
  "started_at": "2026-05-22T09:14:03Z",
  "completed_at": "2026-05-22T11:42:51Z",
  "expected_count": 148231,
  "records_fetched": 148231,
  "page_count": 742,
  "count_mismatch": false
}
```

- `query`, `started_at`, `expected_count` copied from `_META.json` (`query`
  duplicated deliberately so the report is self-contained for the runner).
- `records_fetched`: actual line count across all page files.
- `page_count`: number of page files.
- `count_mismatch`: `records_fetched != expected_count`. Non-blocking.

Timestamps are ISO 8601 UTC strings. No schema-version field (single producer,
single consumer; speculative).

## Invariants

1. **Query isolation.** `_META.query` records the full canonical query (minus
   host prefix, minus cursor, minus API key). For any non-fresh year it must
   equal the current run's canonical query exactly; mismatch → `QueryMismatch`.
   Mixing queries corrupts data.
2. **`_META.json` is immutable** once written, and written before the first
   page file.
3. **Write order per page is fixed**: fetch → write `page-N` → update
   `_CURSOR.json`. This is what makes resume idempotent.
4. **Atomic writes**: tmp + flush + rename for every file. No `fsync` (too slow
   for the benefit at this scale).
5. **`_YEAR_REPORT.json` is immutable** once written; its presence means
   complete. COMPLETE does not require re-validating `_CURSOR.json`.
6. **`write_page` always writes a page file**, even for an empty page (zero-byte
   file). "≥1 page file for any non-fresh year" must hold.
7. **Corruption is loud.** The module manages only the files above. It does not
   guard against external tampering, but any classification ambiguity or
   blatant inconsistency → loud failure from `storage`. No silent recovery.

## Count Check (sanity only)

`_META.json` stores `meta.count` from the first page as `expected_count`.
`finalize_year` counts lines across all page files and records the comparison
in `_YEAR_REPORT.json` (`expected_count`, `records_fetched`, `count_mismatch`).

- **Non-blocking.** A mismatch never blocks completion. Data consolidation is
  out of scope; the runner surfaces the warning in the run report.
- **Smoke alarm, not a guarantee.** It catches *net* count change, not *churn* —
  a concurrent add + delete leaves the count matching while the data is still
  inconsistent. The real defense against drift is that a year usually completes
  within one day, keeping the drift window small.
- Checked **in the worker** (via `finalize_year`) — the only unit that knows
  when a year transitions to complete. The runner only aggregates, never
  computes, keeping the report step crash-trivial.

## Run Report

Built fresh each invocation by the runner from worker outcomes. Pure
aggregation, no disk writes. Reports per-year invocation status and surfaces
count-mismatch warnings from persisted year reports.

The worker is invoked for **every** requested year. A complete, query-matched
year returns a `skipped` outcome immediately, carrying the persisted
`_YEAR_REPORT.json` fields. Nothing is written to disk for a skip. A year
completed during the current invocation returns a `completed` outcome carrying
the newly written year report.

The persisted `_YEAR_REPORT.json` records durable year completion only. It does
not record future skip events or invocation history.

The runner catches `DailyLimitReached`, returns the partial in-memory report for
all outcomes produced so far, records the year where the stop happened, and
stops iterating. The worker does not catch `DailyLimitReached`.

```
@dataclass
class RunReport:
    outcomes: list[YearOutcome]
    status: Literal["complete", "stopped_daily_limit"]
    stopped_year: int | None = None
```

## Error Handling

The connector raises only at fetch time — no in-flight on-disk state to clean
up. 429 is always caught *between* pages, never mid-page-write (guaranteed by
the fixed write order).

| HTTP | Mode |
|---|---|
| `200` | Success |
| `301` | `NonRetryableError` (entity merged; should not occur for list queries) |
| `403` | Exponential backoff + retry to `MAX_RETRIES`, then `RetryExhausted`. Subsecond-burst rate limit; not expected with `requests` (sync). |
| `400`, `404`, other `4xx` | `NonRetryableError` |
| `429` | **Clean stop.** Daily free-credit exhaustion — expected once/day. Connector raises `DailyLimitReached`; worker lets it propagate; runner catches it and returns a partial run report with `status="stopped_daily_limit"`. Resume next day. |
| `5xx` | Exponential backoff + retry to `MAX_RETRIES`, then `RetryExhausted`. |

## Typed Exceptions

Two base classes, five concrete exceptions. The bases let `__main__` and any
future orchestrator catch by category without enumerating leaves.

| Exception | Base | Raised by | Meaning |
|---|---|---|---|
| `ConnectorError` | `Exception` | — | base for all connector failures |
| `DailyLimitReached` | `ConnectorError` | connector | HTTP 429; clean stop, caught by runner |
| `RetryExhausted` | `ConnectorError` | connector | 5xx/403 retries hit `MAX_RETRIES` |
| `NonRetryableError` | `ConnectorError` | connector | 301/4xx; retrying cannot help, raised immediately |
| `StorageError` | `Exception` | — | base for all storage failures |
| `CorruptedState` | `StorageError` | storage | year directory in an invalid file combination |
| `QueryMismatch` | `StorageError` | storage | stored query ≠ current run's canonical query |

`DailyLimitReached` is deliberately *not* a subclass of `NonRetryableError` — a
429 is a clean stop, not an error. The runner catches it as a normal stop path
so it can emit the partial run report.

## Sequencing

1. Pin worker state machine + on-disk layout invariants. *(done)*
2. Pin contracts: storage functions, `fetch_page`, the three JSON schemas,
   typed exceptions. *(done — this doc)*
3. Tests for `process_year` against a fake `fetch_page` closure + tmp
   filesystem. ~80% of test value.
4. Implement against the tests.
5. Runner + `Settings` as a trivial second pass.

## Verify Against the Live API (step 3/4)

Cheap checks to run against real OpenAlex before trusting the contracts:

- A zero-result query returns `meta.count: 0` with no/null `next_cursor`.
- The last page yields an absent/null cursor that normalizes cleanly to `None`.
- `meta.count` for a year-filtered query is stable enough to use as a sanity
  baseline.
- `per_page=200` is accepted and returns up to 200 results.
