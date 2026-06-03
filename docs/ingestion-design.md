# Bronze Ingestion — Design & Contracts (Preliminary)

Preliminary design for the JSONL → Parquet bronze ingestion module. This doc is
written **before implementation**: contracts are pinned where they are settled,
and open questions are flagged explicitly for resolution during a smoke-test
pass once the function bodies stand. Treat **invariants** and **contracts** as
binding; everything marked *(to confirm)* is provisional.

Companion to `extraction-module-design.md`, which produced this module's input.

## Scope

Ingest the raw JSONL page files produced by the extraction module and
materialize them as one Parquet file per year. Bronze is a **thin format
conversion**: it imposes a typed schema, lands nested fields as JSON strings,
performs two minimal record-level integrity checks, and records provenance in a
manifest. It does **not** flatten, deduplicate, normalize, or profile.

Out of scope: unnesting/flattening (dbt staging), semantic deduplication
(silver), null-rate/filter profiling (dbt staging or a separate pass), the
cloud lift to GCS/BigQuery.

Guiding principles, inherited from extraction: **simplicity and specificity**,
**corruption is loud**, **the filesystem is the source of truth**.

## Operational Model

- **Invocation**: manual CLI, run repeatedly during development as extraction
  trickles in new completed years.
- **Shard unit**: one calendar year, mirroring extraction. One Parquet file per
  year.
- **Input**: a `data/extract` directory of per-year extraction shards.
- **Output**: a `data/bronze` directory of per-year Parquet files plus a
  manifest CSV.
- **Resumable & idempotent**: re-running over a range cheaply skips
  already-ingested years and picks up newly-completed ones.
- **Bounded memory**: process strictly one year at a time. Lazy Polars
  (`scan_ndjson` → `sink_parquet`) is the intended approach *(to confirm at
  smoke-test — see Open Questions)*.

## Input Contract

Bronze consumes extraction output and **trusts extraction's integrity within
extraction's own scope**. Extraction guarantees are *report-level* (line counts
match reports, pages contiguous, query-isolated). Extraction explicitly defers
per-record profiling, so bronze inherits **no per-record content guarantees**.

- **Only COMPLETE years are ingested.** A year is COMPLETE iff
  `_YEAR_REPORT.json` is present (extraction's authoritative completion signal).
  Years in FRESH or IN_PROGRESS state within the requested range are skipped
  (recorded in the manifest with a `pending` status — see Manifest).
- A `count_mismatch=true` year (extraction's soft data-drift signal) **is
  ingested normally**. The flag is forwarded into the manifest. It is *not* a
  bronze failure.
- Per-record JSON objects were left untouched by extraction (a `json.loads` →
  `json.dumps` round-trip; verbatim at record level, not byte-identical).

## Record-Level Checks

Bronze performs exactly **two** record-level checks. This is a deliberate,
minimal exception to "trust extraction, no revalidation" — both checks defend
the primary key, which downstream layers should not have to discover is broken.
The set does not grow.

1. **Malformed JSON → loud failure.** A line that does not parse as valid JSON
   is on-disk corruption (extraction wrote only `json.dumps` output). With the
   native Polars reader, a malformed line throws during read; bronze lets the
   year fail loudly rather than pre-filtering. Consistent with extraction's
   "corruption is loud."
2. **Non-null `id` → loud failure.** `id` is the primary key. A null or missing
  `id` fails the year loudly.

ID **format** validation (`W\d+` pattern) is deliberately **not** performed —
it second-guesses OpenAlex's own ID scheme and buys little over non-null.

## Uniqueness Assertion (non-blocking)

Bronze computes, per year, the count of duplicate `id` values
(`duplicate_id_count`) and records it in the manifest. This is a **uniqueness
assertion, not deduplication** — no rows are removed; bronze only surfaces the
number.

- **Non-blocking**, mirroring extraction's treatment of `count_mismatch`:
  recorded, surfaced as a warning, never blocks completion.
- **Cause is genuinely ambiguous** and a duplicate is *not necessarily*
  corruption. Candidates: (a) on-disk corruption, (b) OpenAlex cursor-pagination
  churn — the same work returned across two pages if the source index shifts
  mid-extraction. (b) is a *source* artifact, not an extraction bug, and a loud
  crash would wrongly punish a fine pipeline. Hence non-blocking.
- Extraction's resume logic *overwrites* `page-{next_page}`, so resume-path
  duplication is by-construction unlikely — reinforcing that a duplicate, if
  found, is more likely source churn than an extraction defect.
- Any surfaced warning should be **cause-neutral**: report the duplicate `id`
  and its year; do not attribute it to extraction.

## Schema

Bronze imposes an **explicit 21-column schema**. Typed scalars are typed; the
eight nested fields are landed as **JSON strings** and parsed downstream in dbt
staging (consistent with data model, which places flattening in dbt).

| Column | Polars dtype | Notes |
|---|---|---|
| `id` | `String` | Primary key. Non-null check applies. |
| `title` | `String` | |
| `publication_year` | `Int64` | Also the shard key / partition. |
| `publication_date` | `String` | Date-shaped (`YYYY-MM-DD`) but kept String to avoid malformed-date parse failures. |
| `type` | `String` | |
| `language` | `String` | |
| `is_retracted` | `Boolean` | Missing key → null. |
| `is_paratext` | `Boolean` | Missing key → null. |
| `primary_topic` | `String` | Nested → JSON string. |
| `topics` | `String` | Nested → JSON string. |
| `cited_by_count` | `Int64` | |
| `counts_by_year` | `String` | Nested → JSON string. |
| `cited_by_percentile_year` | `String` | Nested → JSON string. |
| `citation_normalized_percentile` | `String` | Nested → JSON string. |
| `fwci` | `Float64` | |
| `referenced_works_count` | `Int64` | |
| `open_access` | `String` | Nested → JSON string. |
| `doi` | `String` | |
| `ids` | `String` | Nested → JSON string. |
| `keywords` | `String` | Nested → JSON string. |
| `updated_date` | `String` | Full timestamp with microseconds; kept String for the same reason as `publication_date`. |

**Date columns as String**: both `publication_date` and `updated_date` are kept
as `String` rather than `Date`/`Datetime`. Bronze stays thin and must not trip
on a malformed date or timestamp. Typed date handling is deferred to dbt
staging.

### Schema enforcement mechanism *(to confirm at smoke-test)*

Polars' `schema` argument does **not** instruct the JSON parser to leave a
subtree unparsed — a `String` dtype against a JSON object is a type mismatch.
The nested fields are therefore necessarily parsed into Struct/List by
`scan_ndjson`, then **re-encoded to JSON strings** (`.struct.json_encode()` /
equivalent) before the Parquet write.

The choice to land nested fields as String is made for **schema stability**,
not to avoid parsing (Polars parses regardless): every year's Parquet then has
an identical, trivially stable 8-String-column nested footprint, fully
decoupled from OpenAlex struct quirks across years.

The exact mechanism (forced-schema behavior of `scan_ndjson`, faithfulness of
the `json_encode` round-trip) is **to be confirmed by a smoke-test spike**
against real page files. See Open Questions.

### Column-presence contract

`architecture.md` contains the data model; bronze reasserts it at the **schema level**:
the output Parquet has exactly these 21 columns. (Reassertion is schema-level only —
"all 21 columns present in every JSON object" is not meaningful, since OpenAlex
omits keys for null-valued fields.)

## On-Disk Layout

```
{data_root}/extract/{year}/...        # input — extraction shards
{data_root}/bronze/{year}.parquet     # output — one file per year
{data_root}/bronze/manifest.csv       # output — one row per in-range year
```

Output path resolution is parameterised; the GCS lift is a later swap and is
not anticipated to require a design change.

## Idempotency & Resume

- The **per-year Parquet file is the authoritative completion signal** for "this
  year is ingested" — exactly as `_YEAR_REPORT.json` is for extraction.
- **Atomic write**: write `{year}.parquet.tmp`, then rename to `{year}.parquet`.
  Rename is atomic on local disk. A crash leaves a stale `.tmp`, which is
  garbage the next run overwrites. Bronze does not actively clean stale `.tmp`
  files; it ignores them.
- **Skip rule**: a year whose `{year}.parquet` already exists is skipped.
  *(to confirm: skip on mere presence vs. mtime-vs-source — see Open Questions.)*
- The **manifest is never the completion signal** — it is derived, rebuilt
  wholesale each run (see below), and so cannot desync.

## Manifest

A single `manifest.csv` — human-readable, tiny (76 rows for 1950–2026).
**Rebuilt wholesale every run** by scanning the bronze output directory; never
appended. Wholesale rebuild makes it idempotent for free and impossible to
desync from the Parquet files.

The manifest is **global**: it always reflects every year present, regardless
of the `--years` argument of the current run (which scopes *ingestion*, not the
manifest).

One row per in-range year. Columns *(provisional — finalize at smoke-test)*:

| Column | Source | Notes |
|---|---|---|
| `publication_year` | shard key | |
| `status` | bronze | `ingested` / `pending` (extraction incomplete) |
| `query` | extraction `_YEAR_REPORT.json` | what was extracted |
| `expected_count` | extraction report | OpenAlex `meta.count` |
| `records_fetched` | extraction report | extraction's line count |
| `count_mismatch` | extraction report | forwarded soft signal |
| `extraction_completed_at` | extraction report | |
| `bronze_row_count` | bronze | actual rows in the Parquet |
| `duplicate_id_count` | bronze | uniqueness assertion result |
| `bronze_file_path` | bronze | relative path to the Parquet |
| `ingested_at` | bronze | one timestamp per year |

`bronze_row_count` vs. extraction's `records_fetched` is bronze's own count
check: a divergence means bronze lost or duplicated rows — a bronze bug,
distinct from extraction's `count_mismatch`.

### No per-row provenance columns

Bronze adds **zero columns to the records**. All provenance (ingest timestamp,
source, counts) lives in the manifest at year granularity. Per-row
`_ingested_at` would be 14.7 M identical-within-a-year timestamps; per-row
`_source_file` (page-file traceability) is not needed by any analytical
question in `architecture.md`. This supersedes the earlier `_ingested_at` /
`_source_file` sketch and keeps bronze a near-pure format conversion.

## Empty / Zero-Result Years

Extraction's contract allows a zero-result year (one zero-byte
`page-0001.jsonl`). Bronze writes an **empty but fully-schema'd Parquet** for
such a year — it does not crash. Polars' exact behavior on a zero-byte input
file is *(to confirm at smoke-test)*.

## Configuration

Bronze reads configuration from **env vars with CLI overrides** (CLI takes
precedence over env). The CLI-override capability is a deliberate divergence
from extraction (env-only): extraction is a fixed daily prod job, whereas
bronze is under active development *against a dataset extraction is still
growing* — switching env vars between running prod-extraction and
dev-ingestion is friction worth removing.

- `OPENALEX_START_YEAR`, `OPENALEX_END_YEAR` — reused from extraction; the year
  range is constant across extract and ingest in prod.
- **Data directory**: extraction's `OPENALEX_DATA_DIR` currently points
  directly at `.../data/extract` and **extraction is running in prod against
  that definition**. Bronze therefore introduces a **separate
  `OPENALEX_DATA_ROOT`** pointing at `.../data` and appends `/bronze` to its
  destination path. 

The broader question of env vs. CLI vs. config-file for the whole pipeline is
deferred.

## Open Questions / To Confirm at Smoke-Test

Resolved once the function bodies stand and can be run against real page files:

1. **Schema uniformity across years.** Pull one page file per year and inspect
   whether the inferred nested-struct shapes diverge across years. If divergence
   is a non-issue, the JSON-string re-encode is purely about a stable contract;
   if it is real, the re-encode is load-bearing.
2. **`scan_ndjson` forced-schema behavior** — confirm how a forced schema
   interacts with nested fields, and that `.struct.json_encode()` round-trips
   faithfully.
3. **Zero-byte page file** — confirm Polars yields an empty frame (not an
   error) so the empty-Parquet path holds.
4. **Lazy vs. eager** — confirm `scan_ndjson` → `sink_parquet` keeps memory
   bounded on the largest years (~1.5 M records) and choose lazy vs. eager.
5. **Skip rule granularity** — skip on Parquet presence alone, or compare mtime
   against the source `_YEAR_REPORT.json` to catch a re-extracted year.
6. **Final manifest column set** — confirm the provisional columns above.

## Sequencing

1. Pin contracts and flag open questions. *(done — this doc)*
2. Implement the per-year ingestion function (schema, checks, atomic write).
3. Smoke-test against real page files; resolve Open Questions 1–6.
4. Manifest rebuild + CLI/Settings wiring.
