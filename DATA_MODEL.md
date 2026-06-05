# DATA_MODEL.md

## AI Topic Classification

### Rule

A work is flagged as AI (`is_ai = true`) if its `primary_topic.subfield.id`
matches one of the following OpenAlex subfields:

- `Artificial Intelligence`
- `Computer Vision and Pattern Recognition` *(see ablation below)*

Classification and all analytical groupings (subfield share, Gini, half-life)
are derived from `primary_topic` only. The full `topics` array is retained in
bronze but not used for classification.

### Rationale

Using `primary_topic` is simpler, avoids double-counting, and is more
analytically defensible — a work's primary topic reflects its core
contribution. We trust OpenAlex's classification rather than trying to
second-guess it via the secondary topics array.

CV/PR inclusion is a judgment call and is tested as an ablation.

### Ablation

Two classification variants are defined:

| Variant | Subfields included |
|---|---|
| `ai_strict` | Artificial Intelligence only |
| `ai_broad` | Artificial Intelligence + Computer Vision and Pattern Recognition |

All analytical questions (Q1–Q3) are computed for both variants. Differences
are reported.

---

## Bronze Layer: Works Table

**Source**: OpenAlex works entity, filtered to Computer Science field
(`primary_topic.field.id:17`). Year range: 1950 until today.

**Format**: Parquet — one file per `publication_year` shard
(`{bronze_root}/{year}.parquet`), not Hive-partitioned. On upload to GCS, a
Hive-style prefix is added for BigQuery partition pruning; the file itself is
unchanged. See `ARCHITECTURE.md` for the cross-boundary path convention.

**Nesting**: The eight nested fields are landed as **raw JSON strings**
(verbatim, exactly as OpenAlex emitted them) — *not* native Parquet
structs/lists. dbt staging parses and flattens them. The forced-String choice
(over inferring structs and `json_encode`-ing them back) preserves fidelity:
struct round-trip fabricates explicit `null`s for keys a record never had.
See `docs/bronze-design.md`.

**Provenance**: Bronze adds **no per-record columns** — no `_extracted_at`.
All provenance lives at **year granularity** in `{bronze_root}/_MANIFEST.parquet`
(one row per year: query, counts, `ingested_at`, etc.).

### Included columns

Types below are the bronze Parquet dtypes. Scalars are typed; the eight nested
fields are `string (JSON)`. `publication_date` and `updated_date` stay `string`
in bronze — date/timestamp typing is deferred to dbt staging.

| Column | Type | Notes |
|---|---|---|
| `id` | string | OpenAlex work ID, primary key; non-null asserted |
| `title` | string | |
| `publication_year` | int | Shard key |
| `publication_date` | string | Date typing deferred to dbt |
| `type` | string | e.g. article, preprint |
| `language` | string | |
| `is_retracted` | bool | Data quality filter |
| `is_paratext` | bool | Data quality filter |
| `primary_topic` | string (JSON) | Full object: id, display_name, subfield, field |
| `topics` | string (JSON) | Full topic array — retained but not used for classification |
| `cited_by_count` | int | Cumulative total |
| `counts_by_year` | string (JSON) | Year-resolved citations — critical for half-life approximation |
| `cited_by_percentile_year` | string (JSON) | |
| `citation_normalized_percentile` | string (JSON) | |
| `fwci` | float | Field-weighted citation impact |
| `referenced_works_count` | int | |
| `open_access` | string (JSON) | |
| `doi` | string | Deduplication |
| `ids` | string (JSON) | External ID crosswalk |
| `keywords` | string (JSON) | Low signal; retained as cheap insurance |
| `updated_date` | string | Timestamp typing deferred to dbt |

### Excluded columns

All others.