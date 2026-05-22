# DATA_MODEL.md

## AI Topic Classification

### Rule

A work is flagged as AI (`is_ai = true`) if its `primary_topic.subfield.id` matches one of the following OpenAlex subfields:

- `Artificial Intelligence`
- `Computer Vision and Pattern Recognition` *(see ablation below)*

Classification and all analytical groupings (subfield share, Gini, half-life) are derived from `primary_topic` only. The full `topics` array is retained in bronze but not used for classification.

### Rationale

Using `primary_topic` is simpler, avoids double-counting, and is more analytically defensible — a work's primary topic reflects its core contribution. We trust OpenAlex's classification rather than trying to second-guess it via the secondary topics array.

CV/PR inclusion is a judgment call and is tested as an ablation.

### Ablation

Two classification variants are defined:

| Variant | Subfields included |
|---|---|
| `ai_strict` | Artificial Intelligence only |
| `ai_broad` | Artificial Intelligence + Computer Vision and Pattern Recognition |

All analytical questions (Q1–Q3) are computed for both variants. Differences are reported.

### Open questions

- CV/PR inclusion — deferred to analysis time; both ablation variants will be computed.
- Subfield IDs (not just display names) — to be pinned once confirmed via API.

---

## Bronze Layer: Works Table

**Source**: OpenAlex works entity, filtered to Computer Science field (`primary_topic.field.id:17`). Year range: 1950 until today.
**Format**: Parquet, partitioned by `publication_year`.  
**Nesting**: Nested fields (`counts_by_year`, `primary_topic`, `topics`) are kept as-is in bronze. Flattening happens in dbt staging models.

### Included columns

| Column | Type | Notes |
|---|---|---|
| `id` | string | OpenAlex work ID, primary key |
| `title` | string | |
| `publication_year` | int | Partition key |
| `publication_date` | date | |
| `type` | string | e.g. article, preprint |
| `language` | string | |
| `is_retracted` | bool | Data quality filter |
| `is_paratext` | bool | Data quality filter |
| `primary_topic` | struct | Full struct: id, display_name, subfield, field |
| `topics` | list[struct] | Full topic array — retained but not used for classification |
| `cited_by_count` | int | Cumulative total |
| `counts_by_year` | list[struct] | Year-resolved citations — critical for half-life approximation |
| `cited_by_percentile_year` | struct | |
| `citation_normalized_percentile` | struct | |
| `fwci` | float | Field-weighted citation impact |
| `referenced_works_count` | int | |
| `open_access` | struct | |
| `doi` | string | Deduplication |
| `ids` | struct | External ID crosswalk |
| `keywords` | list[struct] | Low signal; retained as cheap insurance |
| `updated_date` | date | |

**Extra**:
| `_extracted_at` | timestamp | ISO 8601 UTC timestamp added during JSONL → Parquet bronze materialization; not present in data source |

### Excluded columns

All others.
