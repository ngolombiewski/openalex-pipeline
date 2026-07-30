# DATA_MODEL.md

## AI Topic Classification and Grouping

### Pinned subfields

Two OpenAlex primary-topic subfields receive explicit analytical treatment:

- `Artificial Intelligence` — `https://openalex.org/subfields/1702`
- `Computer Vision and Pattern Recognition` —
  `https://openalex.org/subfields/1707`

Matching is on the subfield **id**, not the display name: the id is the stable
upstream key, the name is a presentation string. The ids are pinned as
`dbt_project.yml` vars (`subfield_ai`, `subfield_cv_pr`) and applied in the
silver/gold analytical layers.

Classification and all analytical groupings (subfield share, Gini, annual
citation age) are derived from `primary_topic` only. The full `topics` array
is retained in bronze but not used for classification.

### Rationale

Using `primary_topic` is simpler, avoids double-counting, and is more
analytically defensible — a work's primary topic reflects its core
contribution. We trust OpenAlex's classification rather than trying to
second-guess it via the secondary topics array.

Whether CV/PR should be included under an aggregate “AI” label is a judgment
call. The project preserves both the aggregate ablation flags and the
underlying exclusive categories so each analytical question can use the more
informative representation for its measure.

### Derived strict/broad flags

Two classification variants are defined:

| Variant | Subfields included | Subfield ids |
|---|---|---|
| `ai_strict` | Artificial Intelligence only | `1702` |
| `ai_broad` | Artificial Intelligence + Computer Vision and Pattern Recognition | `1702`, `1707` |

Q1 publishes both variants because publication counts and shares are additive.
The flags remain pinned in `silver_works`. Measured against the full corpus,
`ai_strict` is ≈27.5% and `ai_broad` ≈40.0% of CS works (sanity anchor, not a
target).

### Exclusive Q2 and proposed Q3 groups

Q2 uses a mutually exclusive partition because citation-age quantiles are
nonlinear and a combined AI+CV/PR median would hide CV/PR's own distribution:

| Group | Rule |
|---|---|
| `ai` | Primary-topic subfield id `1702` |
| `cv_pr` | Primary-topic subfield id `1707` |
| `rest_cs` | Every other `silver_works` row |

The deployed Q3 remains at individual CS-subfield grain. Its proposed
replacement keeps that grain as the primary comparison and adds the same
exclusive `ai` / `cv_pr` / `rest_cs` partition as a secondary pooled relation,
computed directly over papers because Ginis do not aggregate. Strict/broad
flags continue to label the AI-related subfield rows; they do not create
pooled variant-level statistics. See
`docs/gold-q3-revisit-design.md`.

---

## Bronze Layer: Works Table

**Source**: OpenAlex works entity, filtered to Computer Science field
(`primary_topic.field.id:17`). Year range: 1950 until today.

**Landing-zone rule**: one landing zone = one query. An extraction root and
its bronze root hold year shards of a single filter/select; bronze asserts
query homogeneity across all completed shards before ingesting anything and
fails loudly on a mix. A different filter/select is a different corpus and
runs as a separate pipeline instance with its own roots (and bucket prefix).
Provenance therefore stays at year granularity — no per-record origin columns.

**Format**: Parquet — one file per `publication_year` shard
(`{bronze_root}/{year}.parquet`), not Hive-partitioned. On upload to GCS, a
Hive-style prefix is added for BigQuery partition pruning; the file itself is
unchanged. See `ARCHITECTURE.md` for the cross-boundary path convention.

**Nesting**: The eight nested fields are landed as **raw JSON strings**
(verbatim, exactly as OpenAlex emitted them) — *not* native Parquet
structs/lists. dbt staging parses and flattens them. The forced-String choice
(over inferring structs and `json_encode`-ing them back) preserves fidelity:
struct round-trip fabricates explicit `null`s for keys a record never had.
See `docs/design-archive/bronze-design.md`.

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
| `counts_by_year` | string (JSON) | Year-resolved citations — critical for annual citation-age analysis |
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
