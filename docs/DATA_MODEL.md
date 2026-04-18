# DATA_MODEL.md

## AI Topic Classification

### Rule

A work is flagged as AI (`is_ai = true`) if **any entry** in its `topics` array belongs to one of the following OpenAlex subfields:

- `Artificial Intelligence`
- `Computer Vision and Pattern Recognition` *(see ablation below)*

Classification is applied as a boolean attribute on each work. The work's `primary_topic` subfield is used separately for grouping in Gini and half-life analyses — a work can be "AI-flagged" while belonging to a non-AI primary subfield.

### Rationale

Using the full `topics` array (rather than `primary_topic` only) captures papers where AI is a significant but secondary lens — e.g. a systems paper whose topics include an AI entry. Filtering to `primary_topic` would undercount AI's footprint.

CV/PR is included by default because the subfield is inseparable from modern AI research. This is a judgment call and is tested as an ablation.

### Ablation

Two classification variants are defined:

| Variant | Subfields included |
|---|---|
| `ai_strict` | Artificial Intelligence only |
| `ai_broad` | Artificial Intelligence + Computer Vision and Pattern Recognition |

All analytical questions (Q1–Q3) are computed for both variants. Differences are reported.

### Open questions

- Whether to include specific topics from Signal Processing or HCI subfields. Deferred pending initial analysis.
- Subfield IDs (not just display names) — to be pinned once confirmed via API.

---

## Bronze Layer: Works Table

**Source**: OpenAlex works entity, filtered to Computer Science field.  
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
| `topics` | list[struct] | Full topic array — used for AI classification |
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

### Excluded columns

`abstract_inverted_index`, `authorships`, `institutions`, `funders`, `apc_list`, `apc_paid`, `awards`, `mesh`, `sustainable_development_goals`, `related_works`, `referenced_works`, `locations`, `best_oa_location`, `primary_location`, `content_urls`, `corresponding_author_ids`, `corresponding_institution_ids`, `countries_distinct_count`, `institutions_distinct_count`, `locations_count`, `indexed_in`, `has_content`, `has_fulltext`, `is_xpac`, `created_date`, `updated_date`
