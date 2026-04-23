57361u# Extraction Module — Policy

## Purpose

Extract OpenAlex `works` records for the Computer Science field and land them as raw JSONL page files on local disk. This is the bronze-ingest stage. Downstream Polars → Parquet → GCS is out of scope for this module.

## Scope

**In scope**
- Fetch pages from `/works` via cursor pagination
- Write each page as JSONL to local disk
- Persist cursors for resumption
- Reconcile record counts per year (post-flight check)
- Handle rate limits, credit exhaustion, and transient errors
- Resume cleanly across invocations

**Out of scope**
- GCS upload
- Parquet conversion or any schema enforcement beyond what OpenAlex returns
- Other OpenAlex entities (authors, sources, institutions, topics)
- Incremental re-pulls or change-data-capture
- Parallelism across years (sequential is fine; OpenAlex credit budget is the bottleneck, not wall time)

## Operational Model

The module is an **idempotent, resumable job** invoked daily until the full CS corpus is on disk.

- On startup: scan the output tree, determine which (year, page) tuples already exist, resume from the gap.
- On HTTP 429 (daily credits exhausted): stop cleanly, log final state, exit 0. Expected outcome, not an error.
- On transient error (5xx, timeout, connection reset):floor is 1950, ceiling is datetime.now().year evaluated per-invocation; the current year is a partial snapshot by design. retry with backoff. After N retries, fail loudly.
- On re-run: no flags needed. "Do what's left" is the default behavior.

## Data Layout

```
data/raw/works/
  year=1980/
    page_00001.jsonl
    page_00001.cursor      # cursor for the NEXT page
    page_00002.jsonl
    page_00002.cursor
    ...
    _META.json             # meta.count + first-seen timestamp, written once per year
    _SUCCESS               # written iff count reconciliation passes
  year=1981/
    ...
```

- One directory per `publication_year`.
- Pagination is per-year (one cursor walk per year), not global.
- Each page is a JSONL file of up to 200 records.
- Each page has a sibling `.cursor` file containing the cursor string needed to fetch the *next* page. Final page's cursor file contains the empty string or a sentinel.
- `_META.json` is written on the first successful page of a year and records `meta.count` plus fetch start timestamp.
- `_SUCCESS` marker is written only after all pages are downloaded AND the record count reconciles against `_META.json`.

**Year processing order**: ascending. Oldest years are smallest — finishing them first gives early wins and a fast-fail signal if something's wrong.

**Year range**: Floor is 1950, ceiling is datetime.now().year evaluated per-invocation; the current year is a partial snapshot by design.

## Invariants

1. **Atomic writes.** Write page to `page_NNNNN.jsonl.tmp`, fsync, rename. Same for `.cursor`. No partial files on disk, ever.
2. **Page file ↔ cursor file pairing.** A page file exists iff its cursor file exists. Startup scan validates this; orphans are deleted and re-fetched.
3. **Count reconciliation.** Sum of records across page files for a year must equal `meta.count` recorded in `_META.json`. Mismatch → no `_SUCCESS` marker → loud error.
4. **No silent skips.** Any page that returns fewer records than expected (other than the final page) is a reconciliation failure.
5. **Snapshot stamp.** Each record, at write time, gets an `_extracted_at` field (ISO 8601 UTC timestamp) injected into the JSON. This is the snapshot column. `updated_date` is included in the select list but serves a different purpose (record version, not fetch time).
6. HTTP layer returns parsed response or raises a typed exception; never None, [], or sentinel. CreditsExhausted and RateLimited are distinct exception types.

## Configuration Surface

All via environment variables (pydantic-settings), with sensible defaults:

| Variable | Purpose | Default |
|---|---|---|
| `OPENALEX_API_KEY` | Required. Authenticates requests. | — |
| `OPENALEX_OUTPUT_DIR` | Root of output tree. | `data/raw/works` |
| `OPENALEX_FILTER` | Override default filter. Dev/test use only. | `primary_topic.field.id:17` |
| `OPENALEX_YEAR_RANGE` | Override year range. Dev/test use only. Format: `1980-2025` or `2024`. | full range from API |
| `OPENALEX_PER_PAGE` | Page size. | 200 |
| `OPENALEX_MAX_RETRIES` | Retries on transient errors. | 5 |
| `OPENALEX_LOG_LEVEL` | loguru level. | `INFO` |

No CLI flags beyond what a thin entrypoint needs (`python -m extraction` or similar). Development sampling is done by overriding `OPENALEX_FILTER` and `OPENALEX_YEAR_RANGE`, not by a separate code path.

## Field Selection

The set of fields returned is fixed for the project and defined as a single module-level constant `SELECT_FIELDS` matching DATA_MODEL.md bronze columns. Every API call uses `select=<SELECT_FIELDS>`. Changing the list is a deliberate schema change, not a configuration knob.

## Failure Model

| Condition | Behavior |
|---|---|
| HTTP 429 | Stop cleanly, log, exit 0 (daily credit exhausted). |
| HTTP 403 | Exponential backoff, up to MAX_RETRIES (transient, sub-second burst limit) |
| HTTP 5xx, timeout, connection reset | Exponential backoff, up to `OPENALEX_MAX_RETRIES`. |
| HTTP 4xx other than 429/403 | Fail loudly. Likely a bug. |
| Count reconciliation mismatch | Fail loudly. Do not write `_SUCCESS`. |
| Orphan page or cursor file on startup | Delete, log, continue. |
| Disk full / write error | Fail loudly. |

## Observability

- loguru structured logs: year, page number, records fetched, cumulative progress, cursor.
- At end of run: summary line per year (pages fetched, records fetched, status: complete/in-progress/failed).
- Year `_META.json` doubles as machine-readable progress state.

## Non-Goals Worth Stating Explicitly

- No abstract "OpenAlex client" for arbitrary entities. `works` only.
- No in-process parallelism. One cursor walk at a time.
- No caching layer. OpenAlex is the source of truth per run.
- No pluggable storage backend. Local disk only.
- No schema validation of returned records. Trust the API; validate downstream in dbt staging.

---

If this reads right, Step 2 can take this and design the concrete class/function surface + test plan. Flag anything you want tightened, loosened, or removed.
