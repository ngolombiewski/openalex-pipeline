# OpenAlex Pipeline — Architecture

## Project

DE Zoomcamp capstone. End-to-end batch data pipeline on OpenAlex data, answering three analytical questions about AI's trajectory in computer science research:

1. **The Takeover** — How has AI's share of CS research grown over time?
2. **The Shelf Life** — Do AI papers age faster? (citation half-life by subfield)
3. **The Winner's Game** — Is citation impact more concentrated in AI than other CS subfields? (Gini coefficient)

**Pipeline shape:** OpenAlex CLI → JSONL → Polars → Parquet → GCS → BigQuery → dbt → Streamlit

Orchestrated by Dagster as software-defined assets. Cloud infrastructure managed with Terraform.

---

## Data Model

### AI Topic Classification

A work is flagged as AI (`is_ai = true`) if its `primary_topic.subfield.id` matches one of the defined AI subfields. Classification and all analytical groupings are derived from `primary_topic` only; the full `topics` array is retained in bronze but not used for classification.

Two ablation variants are defined:

| Variant | Subfields included |
|---|---|
| `ai_strict` | Artificial Intelligence only |
| `ai_broad` | Artificial Intelligence + Computer Vision and Pattern Recognition |

All three analytical questions are computed for both variants; differences are reported.

See `docs/adr/001-ai-topic-classification.md` for the rationale.

### Bronze Works Table

**Source:** OpenAlex `works` entity, filtered to Computer Science field (`primary_topic.field.id:17`). Year range 1950 to present.
**Format:** Parquet, one file per `publication_year`.
**Nesting:** Nested fields are landed as JSON strings. Flattening happens in dbt staging.

| Column | Polars dtype | Notes |
|---|---|---|
| `id` | `String` | Primary key. Non-null enforced at ingest. |
| `title` | `String` | |
| `publication_year` | `Int64` | Shard key / partition. |
| `publication_date` | `String` | Kept String; typed handling deferred to dbt. |
| `type` | `String` | e.g. article, preprint |
| `language` | `String` | |
| `is_retracted` | `Boolean` | Data quality filter. |
| `is_paratext` | `Boolean` | Data quality filter. |
| `primary_topic` | `String` | Nested → JSON string. |
| `topics` | `String` | Nested → JSON string. Retained but not used for classification. |
| `cited_by_count` | `Int64` | Cumulative total. |
| `counts_by_year` | `String` | Nested → JSON string. Critical for citation half-life. |
| `cited_by_percentile_year` | `String` | Nested → JSON string. |
| `citation_normalized_percentile` | `String` | Nested → JSON string. |
| `fwci` | `Float64` | Field-weighted citation impact. |
| `referenced_works_count` | `Int64` | |
| `open_access` | `String` | Nested → JSON string. |
| `doi` | `String` | Deduplication. |
| `ids` | `String` | Nested → JSON string. External ID crosswalk. |
| `keywords` | `String` | Nested → JSON string. Low signal; retained as cheap insurance. |
| `updated_date` | `String` | Kept String; typed handling deferred to dbt. |

See `docs/adr/003-bronze-nested-fields-as-json-strings.md` for the rationale on JSON-string encoding.

---

## Module Topology

### Extraction

Extracts OpenAlex `works` for the CS field, landing raw records as JSONL page files on local disk. Raw extraction only — no per-record transformation.

**Five subunits:**

| Unit | Form | Responsibility |
|---|---|---|
| `Settings` | Pydantic `BaseSettings` | Config from env vars. API key, query params required. |
| runner | `run()` | Builds canonical query, loops years, aggregates run report. |
| worker | `process_year()` | Paginates one year shard. Year state machine. |
| connector | `fetch_page()` | Single API call with retry/backoff. Injected as a closure. |
| storage | `storage.py` | All filesystem I/O. Five public functions. |

**On-disk layout:**

```
{data_dir}/{year}/
  _META.json          # written once at year start; immutable
  _CURSOR.json        # resume pointer; updated after every page write
  page-0001.jsonl     # one file per API page, up to 200 records
  page-0002.jsonl
  ...
  _YEAR_REPORT.json   # written last; its presence = year complete
```

**Year states:** A year is `FRESH` (directory absent/empty), `IN_PROGRESS` (`_META.json` + `_CURSOR.json` + ≥1 page file, no report), or `COMPLETE` (`_YEAR_REPORT.json` present). Any other combination raises `CorruptedState`.

**Resume:** `_CURSOR.json` always holds the cursor for the *next* page to write. A crash costs at most one re-fetched page on resume; no staleness check is needed.

**Shard unit:** one calendar year. Sequential — the OpenAlex daily credit budget (~2M records) is the bottleneck, not wall time.

### Ingestion

Converts extraction JSONL page files to one Parquet file per year (bronze layer). Thin format conversion: imposes schema, performs minimal integrity checks, records provenance in a manifest. No flattening, deduplication, or profiling.

See `docs/ingestion-design.md` for the current design and open questions. This module is not yet fully implemented.

---

## Contracts & Interfaces

### Extraction Storage Contract

Five public functions in `storage.py` (all take `root: Path, year: int` as leading args):

```
classify_year(query: str) -> YearStatus
    # Classifies year directory state. Checks stored query for non-fresh years.
    # Raises: CorruptedState, QueryMismatch

initialize_year(query: str, meta_count: int) -> None
    # Writes _META.json then _CURSOR.json. Called once per fresh year.

write_page(records: list[dict], next_cursor: str | None, page_number: int) -> None
    # Writes page-{page_number}.jsonl, then updates _CURSOR.json. Write-only.
    # Always writes, even for an empty page (zero-byte file).

finalize_year() -> YearReport
    # Counts lines across all page files, writes _YEAR_REPORT.json, returns report.

read_year_report() -> YearReport
    # Reads and returns _YEAR_REPORT.json. Called on the COMPLETE skip path.
```

### Extraction Connector Contract

```
fetch_page(query: str, cursor: str, api_key: str)
    -> tuple[list[dict], str | None, int]
    #  (records, next_cursor, meta_count)
```

`query` is the canonical query string (excluding host prefix, cursor, and API key), stored verbatim in `_META.json` and used for query-isolation comparison. The connector assembles the full URL; it treats `query` as opaque.

### Query Construction

The runner builds the canonical query once per year:

```
works?filter=primary_topic.field.id:17,publication_year:{year}&select={columns}&per_page=200
```

`select` is pinned to the 21 bronze columns. This string is the query-isolation key.

### Typed Exceptions

| Exception | Base | Raised by | Meaning |
|---|---|---|---|
| `ConnectorError` | `Exception` | — | Base for connector failures |
| `DailyLimitReached` | `ConnectorError` | connector | HTTP 429; clean daily stop |
| `RetryExhausted` | `ConnectorError` | connector | 5xx/403 retries hit `MAX_RETRIES` |
| `NonRetryableError` | `ConnectorError` | connector | 301/4xx; retrying cannot help |
| `StorageError` | `Exception` | — | Base for storage failures |
| `CorruptedState` | `StorageError` | storage | Year directory in invalid state |
| `QueryMismatch` | `StorageError` | storage | Stored query ≠ current run's query |

`DailyLimitReached` is not a subclass of `NonRetryableError` — a 429 is a clean stop, not an error. The runner catches it and returns a partial run report.

### HTTP Error Handling (Extraction Connector)

| HTTP | Behavior |
|---|---|
| `200` | Success |
| `301` | `NonRetryableError` |
| `403` | Exponential backoff + retry to `MAX_RETRIES`, then `RetryExhausted` |
| `400`, `404`, other `4xx` | `NonRetryableError` |
| `429` | `DailyLimitReached` — clean stop; runner returns partial report |
| `5xx` | Exponential backoff + retry to `MAX_RETRIES`, then `RetryExhausted` |

### Extraction Invariants

1. `_META.json` is immutable once written and is written before the first page file.
2. Write order per page is fixed: fetch → write `page-N` → update `_CURSOR.json`. This makes resume idempotent.
3. All file writes are atomic (tmp + flush + rename).
4. `_YEAR_REPORT.json` is immutable once written; its presence means complete.
5. `write_page` always writes a page file, even for an empty page (zero-byte file).
6. Corruption is loud: any classification ambiguity → `CorruptedState`. No silent recovery.
7. Query isolation: stored query must equal current run's canonical query for any non-fresh year; mismatch → `QueryMismatch`.

---

## Configuration

| Env var | Used by | Notes |
|---|---|---|
| `OPENALEX_API_KEY` | extraction | Required |
| `OPENALEX_DATA_DIR` | extraction | Points to `data/extract/`; do not redefine |
| `OPENALEX_START_YEAR` | extraction, ingestion | Year range start |
| `OPENALEX_END_YEAR` | extraction, ingestion | Year range end |
| `OPENALEX_BRONZE_DIR` | ingestion | Separate from `OPENALEX_DATA_DIR` to avoid touching running extraction config |

See `env.example` for all available variables.
