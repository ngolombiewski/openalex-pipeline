# Bronze Ingestion — Design & Contracts

> **Status: as-built.** Reconciled with the green-light implementation under
> `src/openalex_pipeline/bronze/` (tests green, ruff + pyright clean).
> `contracts.py` has been removed and the code is now the source of truth; this
> document is retained as the design record and rationale.

Settled design for the JSONL → Parquet bronze materialization step. Consumes the
output of the extraction module (`extraction-module-design.md`) and produces the
bronze works table described in `docs/DATA_MODEL.md`.

Treat **invariants**, **the schema**, and **contracts** as binding; everything
else is rationale. Every non-trivial decision below was verified against real
production extract data with a spike (`scripts/bronze_ingest_spike.py`); spike
findings are cited inline where they pin a decision.

## Scope

Ingest the raw JSONL files produced by the extraction module and convert them to
Parquet using Polars. One Parquet file per calendar-year shard. Bronze is a
**thin format conversion**: land the data mostly intact, impose an explicit
schema, record provenance in a manifest.

Bronze adds the `_extracted_at`-equivalent provenance at **year granularity in the manifest**, not per record (see *Provenance*).

Guiding principles, inherited from the extraction module: **simplicity and
specificity**. This is a pipeline-specific step, not a general ingestion tool.

### Non-goals

Explicitly **out of scope** for bronze, deferred to dbt staging or silver:

- Unnesting / flattening nested fields — they are landed as JSON strings.
- Semantic deduplication (same work via two DOIs, preprint vs. published).
- Consistency checks beyond the integrity assertions in *Integrity Checks*.
- A full null-rate / filter-conformance profiling pass over all records.
- Typing of date fields — `publication_date` and `updated_date` stay `String`.

## Operational Model

- **Invocation**: manual CLI. Input is a data directory and a year range; bronze
  converts every **completed** year in the range to Parquet.
- **Shard unit**: one calendar year — the same shard unit as extraction. One
  input year directory → one output Parquet file.
- **Completed years only.** A year is ingestible iff extraction marked it
  COMPLETE (`_YEAR_REPORT.json` present). In-progress and fresh years in the
  requested range are skipped, not failed (see *Manifest* for how they surface).
- **Resumable and idempotent.** Re-running over a range cheaply skips
  already-ingested years and picks up newly-completed ones. This matters: bronze
  will be iterated on for weeks while extraction trickles the corpus in daily.
- **Bounded memory.** Bronze processes one year at a time. The largest CS year
  (~1.5 M records) is collected as a single frame; this is well within memory
  and keeps the implementation simple. No cross-year frame is ever held.

## On-Disk Layout

```
{bronze_root}/
  1950.parquet
  1951.parquet
  ...
  2004.parquet
  _MANIFEST.parquet     # one row per year in the requested range; rebuilt each run
```

The presence of `{year}.parquet` is the authoritative signal that the year is
fully ingested. There is no separate `_SUCCESS` marker — matching extraction's
deliberate rejection of one. Atomicity is guaranteed by tmp + rename (see
*Invariants*), so a `{year}.parquet` that exists is necessarily complete.

The manifest is **derived, never authoritative** — it is rebuilt wholesale from
the output directory on every run and cannot desync from the Parquet files.

## Year State & Idempotency

Bronze classifies each requested year by inspecting two things: the extraction
output directory and the bronze output directory.

| State | Condition | Action |
|---|---|---|
| **INGESTED** | `{bronze_root}/{year}.parquet` exists | Skip; year already done |
| **READY** | extraction `_YEAR_REPORT.json` present, no bronze Parquet | Ingest |
| **PENDING** | extraction year not COMPLETE (or absent) | Skip; not yet ingestible |

The skip rule is **presence of the output Parquet**. No mtime comparison, no
content hash. A year is either done or not; if extraction's output for a year
changes after bronze has ingested it, that is outside the normal pipeline flow
and bronze does not defend against it (consistent with extraction's stance on
external tampering). To force re-ingestion, delete the year's Parquet.

`PENDING` years are expected and normal during the ~1-week extraction window —
they are not errors. They appear in the manifest with `status = "pending"` so a
single manifest read shows pipeline progress at a glance.

## Schema

Bronze imposes an **explicit Polars schema** on read. Schema inference is not
used. Inference is both slow at 14.7 M heterogeneous records and unsafe: sparse
records cluster in the long tail (later API pages, obscure works), so a
first-page sample looks uniform while deep pages are not. An explicit schema
also makes scalar type-conformance a read-time invariant (see *Integrity
Checks*).

### The 21-column schema

Typed scalars; nested fields as `String` (raw JSON, see below).

| Column | Polars dtype | Notes |
|---|---|---|
| `id` | `String` | Primary key; non-null asserted |
| `title` | `String` | |
| `publication_year` | `Int64` | Shard key |
| `publication_date` | `String` | Date typing deferred to dbt |
| `type` | `String` | |
| `language` | `String` | |
| `is_retracted` | `Boolean` | |
| `is_paratext` | `Boolean` | |
| `primary_topic` | `String` | Nested — raw JSON |
| `topics` | `String` | Nested — raw JSON |
| `cited_by_count` | `Int64` | |
| `counts_by_year` | `String` | Nested — raw JSON |
| `cited_by_percentile_year` | `String` | Nested — raw JSON |
| `citation_normalized_percentile` | `String` | Nested — raw JSON |
| `fwci` | `Float64` | Nullable; ~3.7% source-null in 2002 |
| `referenced_works_count` | `Int64` | |
| `open_access` | `String` | Nested — raw JSON |
| `doi` | `String` | |
| `ids` | `String` | Nested — raw JSON |
| `keywords` | `String` | Nested — raw JSON |
| `updated_date` | `String` | Date typing deferred to dbt |

Eight nested columns (`primary_topic`, `topics`, `counts_by_year`,
`cited_by_percentile_year`, `citation_normalized_percentile`, `open_access`,
`ids`, `keywords`) are landed as `String`. dbt staging parses them.

### Nested fields: forced-String, not struct round-trip

`scan_ndjson` is given the schema above with the eight nested columns typed as
`String`. Polars then lands each nested object/array as its **raw JSON text,
verbatim** — the object exactly as OpenAlex emitted it.

The rejected alternative was: infer the nested fields as structs, then
`struct.json_encode()` them back to String. **This is rejected on fidelity
grounds.** `struct.json_encode()` first forces Polars to infer a *unified*
struct type across all records — the struct gains a field for every key seen in
*any* record — and then materializes those keys as explicit `null` in records
that never had them. The spike confirmed this concretely: under struct-encode,
`ids` objects gain `pmid: null` for records whose source `ids` had no `pmid`
key at all. Forced-String preserves the original object with missing keys
omitted.

For a bronze layer whose purpose is landing the data intact, struct-encode
*fabricates* data. Forced-String does not. The forced-String path was verified:
full-year collects of 1950 (3,583 rows) and 2002 (294,367 rows) succeeded, a
cross-year concat succeeded (297,950 rows), forced nested strings are valid
JSON, and they match the raw source values.

### Boundary of the JSON guarantee

Every JSONL line was valid JSON **at extraction write time** — the extraction
connector did `json.loads` on every record before `write_page` re-serialized
it. Bronze does **not** independently re-defend against post-write disk
corruption. If a line is malformed on disk, Polars' read fails loud and the year
fails — which is the desired behavior, consistent with extraction's "corruption
is loud" stance.

Bronze guarantees nothing about the *internal* structure of nested fields. They
are landed as opaque strings; a nested field containing a malformed JSON
fragment would pass through bronze untouched. dbt's nested-JSON parsing is the
first step that would catch it. This is an accepted boundary, not a gap.

## Ingestion Algorithm

For each year in the requested range:

```
1. Classify (INGESTED / READY / PENDING).
2. INGESTED or PENDING -> skip, record manifest row, continue.
3. READY:
   a. scan_ndjson(page_files, schema=BRONZE_SCHEMA)   # explicit schema
   b. assert non-null id                  (loud failure on violation)
   c. assert row_count == records_fetched  (loud failure on violation)
   d. count duplicate ids  (non-blocking; recorded in manifest)
   e. write {year}.parquet.tmp, then rename to {year}.parquet  (atomic)
   f. record manifest row.
4. After all years: rebuild and write _MANIFEST.parquet wholesale.
```

### Empty-year path

A zero-result year is a valid extraction state: a single zero-byte
`page-0001.jsonl`. The spike confirmed `scan_ndjson` **fails on a zero-byte
file**. Bronze therefore special-cases it: when a year's only page file is
empty, bronze writes an **empty Parquet carrying the full 21-column schema**
(an empty frame typed by `BRONZE_SCHEMA`). Downstream `scan` of an empty year
then behaves like any other year. No CS year in 1950–2024 is expected to be
empty, but the extraction contract permits it, so bronze handles it.

The empty path is keyed on *exactly* one zero-byte `page-0001.jsonl`. Any other
zero-byte combination — a zero-byte page alongside non-empty pages, or multiple
zero-byte pages — is not a state extraction can produce, so it fails loud as
`CorruptedState` rather than being treated as a (partial) empty year.

### Atomic write

Every Parquet file (year files and the manifest) is written to a `.tmp` path and
renamed into place. Rename is atomic on local disk. A crash mid-write leaves a
`{year}.parquet.tmp` that is simply overwritten on the next run; bronze does not
proactively clean stale `.tmp` files. This mirrors extraction's atomic-write
discipline.

## Integrity Checks

Bronze performs exactly the checks below — no more. It explicitly **trusts the
extraction module's integrity within extraction's own scope** and does not
re-validate page counts, line counts, or page contiguity.

| Check | Mode | Detail |
|---|---|---|
| Non-null `id` | **Loud** | A null primary key is a defect; the year fails. A record-level integrity assertion. |
| `bronze_row_count` == `records_fetched` | **Loud** | The Parquet row count must equal extraction's asserted line count (`_YEAR_REPORT.json`). Asserted before the write. Duplicates count equally on both sides, so the only ways to diverge are bronze losing/multiplying rows or a page file truncated on disk — both defects, neither source churn. Distinct from extraction's non-blocking `count_mismatch`. |
| Scalar type conformance | **Loud (free)** | The forced schema makes this a read-time invariant. The spike confirmed `scan_ndjson` *raises* `ComputeError` on a type-mismatched scalar — it does not silently coerce to null. Every scalar in all 21 columns is implicitly type-checked on read. Bronze catches the `ComputeError` and re-raises it as `CorruptedState`, so it and malformed JSONL surface as one loud, bronze-typed exception. The catch is narrowed to `ComputeError` on purpose: an unexpected, non-`ComputeError` Polars error propagates as itself rather than being mislabeled "corruption". |
| Duplicate `id` count | **Non-blocking** | Count of `id` values appearing more than once in the year. Recorded in the manifest as `duplicate_id_count`. Not a dedup — nothing is removed. |
| `count_mismatch` (forwarded) | **Non-blocking** | Extraction's `count_mismatch` flag is carried into the manifest verbatim. A count-mismatched year is *not* a bronze failure. |

On the **`id`-format regex** (`W\d+`): deliberately **not** done. Non-null is the
defensible primary-key assertion; format validation second-guesses OpenAlex's
own ID scheme and is the kind of speculative strictness this pipeline avoids.

On **duplicate `id` being non-blocking**: the cause of a duplicate is genuinely
ambiguous. It is *not* necessarily an extraction bug — extraction's resume logic
overwrites page files by design, so resumes do not duplicate. The live causes
are on-disk corruption *or* OpenAlex returning the same work across two cursor
pages (source-side churn, which extraction's own count check admits it cannot
catch). Because one of the causes (source churn) is not corruption and not
bronze's fault, a loud crash would sometimes be wrong. Bronze records the count
as a smoke alarm — parallel to how extraction treats `count_mismatch` — and
leaves diagnosis to a human. Any surfaced message must be cause-neutral.

## Provenance & the Manifest

`_MANIFEST.parquet` is a small table — one row per year in the requested range,
76 rows for a full 1950–2026 corpus. It is **rebuilt wholesale every run** by
scanning the bronze output directory and reading the corresponding extraction
year reports. It is never appended to and never the source of truth, so it
cannot desync.

The manifest carries **all provenance at year granularity**. This keeps bronze a near-pure format conversion — zero columns
added to the data.

### Manifest columns (one row per year)

| Column | Source | Notes |
|---|---|---|
| `publication_year` | shard key | `Int64` |
| `status` | bronze | `ingested` / `ready` / `pending`. `ready` is representable but rare in practice (a year whose report is present but which was not ingested this run) — the manifest is normally built after all `ready` years are ingested. |
| `query` | extraction `_YEAR_REPORT` | What was extracted; makes the manifest self-contained |
| `expected_count` | extraction `_YEAR_REPORT` | OpenAlex `meta.count` at extraction time |
| `records_fetched` | extraction `_YEAR_REPORT` | Extraction's line count |
| `count_mismatch` | extraction `_YEAR_REPORT` | Forwarded non-blocking flag |
| `extraction_completed_at` | extraction `_YEAR_REPORT` | From the report's `completed_at` |
| `bronze_row_count` | bronze | Actual rows in `{year}.parquet` |
| `duplicate_id_count` | bronze | Non-blocking duplicate-`id` count |
| `bronze_file_path` | bronze | Path **relative to `bronze_root`** (the string `{year}.parquet`). Deliberately asymmetric with `YearIngestResult.bronze_file_path`, which is the absolute path for a mid-run caller. |
| `ingested_at` | bronze | The Parquet's **mtime** (`Datetime("us", "UTC")`), not "now" — so a manifest rebuild never re-stamps an already-ingested year. |

`bronze_row_count` vs. `records_fetched` is bronze's own count check, and it is
**loud, not just recorded**: `ingest_year` asserts they are equal before writing
the Parquet (see *Integrity Checks*), so any year that has a Parquet has already
passed it — a divergence means bronze lost/duplicated rows or a page was
truncated on disk, both defects distinct from extraction's `count_mismatch`. The
manifest carries both columns for at-a-glance visibility; for an INGESTED year
they are equal by construction. `pending` rows carry only the columns knowable
without ingestion; bronze-side columns are null for them.

## Invariants

1. **Output Parquet presence = completion.** `{year}.parquet` exists iff the
   year is fully ingested. The manifest is derived and never authoritative.
2. **Atomic writes.** Every Parquet (year files and manifest) is written
   tmp + rename. A file that exists is necessarily complete.
3. **Explicit schema, no inference.** All 21 columns are read under
   `BRONZE_SCHEMA`. The eight nested columns are `String` (raw verbatim JSON);
   the rest are typed scalars.
4. **Scalar type-conformance is a read-time invariant.** A scalar that does not
   match its forced dtype raises `ComputeError`, which bronze re-raises as
   `CorruptedState` and fails the year. Bronze does not silently coerce.
5. **Non-null `id` and row-count match.** Every record has a non-null `id`, and
   the Parquet row count equals extraction's `records_fetched` — both asserted
   loud before the year's Parquet is written.
6. **Manifest is rebuilt wholesale.** Never appended. Always reflects the full
   output directory, regardless of the current run's year range — the year
   range scopes *ingestion*, not the manifest.
7. **Corruption is loud.** Malformed JSONL on disk, a scalar that violates its
   dtype, a `_YEAR_REPORT.json` present with zero page files, or a disallowed
   zero-byte page combination all fail loud as `CorruptedState` — no silent
   recovery. Read-time failures reach bronze as Polars `ComputeError` and are
   wrapped; an unexpected non-`ComputeError` Polars error is left to propagate
   as itself rather than be mislabeled corruption.

## Module Layout

The implemented module lives at `src/openalex_pipeline/bronze/` and is split
into six files. The split mirrors the natural test seams (one source file per
test target) and pins a clean dependency DAG: no cycles, no surprises.

| File | Contents |
|---|---|
| `schema.py` | `BRONZE_SCHEMA`, `NESTED_COLUMNS` |
| `errors.py` | `BronzeError`, `CorruptedState`, `IntegrityError` |
| `core.py` | `YearState`, `YearIngestResult`, `classify_year`, `ingest_year`, `write_empty_year` |
| `manifest.py` | `build_manifest`, `write_manifest` |
| `runner.py` | `run` |
| `__main__.py` | `resolve_roots`, `build_years_list`, `parse_args`, `main` |

### Dependency direction

`schema` and `errors` are leaves. `core` imports both. `manifest` imports
`schema` and `errors`. `runner` imports `core` and `manifest`. `__main__`
imports `runner`. `core` does not import `manifest` and `manifest` does not
import `core` — they are sibling concerns (ingestion vs. derived state) and
the runner is the only place that touches both.

A consequence of the sibling split: `manifest` re-derives each year's status
directly from the filesystem (Parquet exists → `ingested`; report exists →
`ready`; else `pending`) rather than calling `core.classify_year`. This keeps
the decoupling intact at the cost of a small, deliberate logic echo. The tiny
atomic-write helper (tmp + rename) is likewise duplicated in `core` and
`manifest` rather than introducing a shared utility module outside the
six-file layout.