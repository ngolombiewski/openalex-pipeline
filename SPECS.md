# SPECS.md — Project Specification

## Narrative

**"AI Is Eating CS — But How Durable Is Its Research?"**

AI now dominates CS publication volume. But quantity isn't impact. This project examines three questions:

1. **The Takeover** — How has AI's share of CS research grown over time?
2. **The Shelf Life** — Do AI papers age faster (citation half-life by subfield)?
3. **The Winner's Game** — Is citation impact more concentrated in AI than other CS subfields (Gini coefficient)?

## Data Source

**OpenAlex** — open catalog of 270M+ scholarly works. We use the **works** entity only, filtered to Computer Science.

### Ingestion Strategy

**Bulk download via OpenAlex CLI** (`openalex-official` package):
- Filter: CS field (field-level topic filter)
- Output: JSON files (one per work), converted to Parquet via Polars
- Scope: ~20M works. For development, filter to recent decades (e.g., 2000–2025). Full pull for production run.

**Fields to extract:**

| Field | Source path | Notes |
|---|---|---|
| `work_id` | `id` | OpenAlex ID (e.g., W2741809807) |
| `publication_year` | `publication_year` | Integer |
| `cited_by_count` | `cited_by_count` | Cumulative, not time-resolved |
| `type` | `type` | article, book, dataset, etc. |
| `is_oa` | `open_access.is_oa` | Boolean |
| `topic_id` | `primary_topic.id` | |
| `topic_name` | `primary_topic.display_name` | |
| `subfield_id` | `primary_topic.subfield.id` | Key grouping level for analysis |
| `subfield_name` | `primary_topic.subfield.display_name` | |
| `field_id` | `primary_topic.field.id` | Should be CS for all rows |
| `field_name` | `primary_topic.field.display_name` | |
| `domain_id` | `primary_topic.domain.id` | |
| `domain_name` | `primary_topic.domain.display_name` | |

### What we skip and why

- **Authorships/institutions**: Not needed for the analytical questions. Would 5x the data volume.
- **Abstract/fulltext**: Not needed.
- **Referenced works / citation graph**: Would enable richer analysis (tile 3 especially) but massively increases scope. Saved for v2.

## Pipeline Architecture

```
OpenAlex CLI → JSON → Polars → Parquet (local)
    → GCS (data lake)
        → BigQuery (external table or LOAD)
            → dbt staging → intermediate → marts
                → Streamlit dashboard
```

Orchestrated by **Dagster** as a single DAG of software-defined assets.

## dbt Model Layers

### Staging (`stg_`)
- `stg_works`: Clean, typed, flat table from raw Parquet/BigQuery source. Filter out paratexts (`type != 'paratext'`). Cast types.
- `stg_topics`: Deduplicated dimension table of topic → subfield → field → domain extracted from works.

### Intermediate (`int_`)
- `int_works_enriched`: Join works to topics dimension. Add derived fields:
  - `years_since_publication` (current_year - publication_year)
  - `is_ai_subfield` (flag based on AI-related subfield IDs — define explicitly, not by string matching)
  - `citation_age_bucket` (for half-life analysis)

### Marts (`marts_`)
- `mart_ai_share`: Yearly counts and share of AI vs non-AI works in CS. Powers Tile 1.
- `mart_citation_halflife`: Median/percentile citation counts by subfield × years_since_publication. Powers Tile 2. (Note: this is an approximation since we lack time-resolved citation data — document this limitation.)
- `mart_citation_gini`: Gini coefficient of `cited_by_count` by subfield × year. Powers Tile 3.

### Tests
- `not_null` on all IDs, `publication_year`
- `accepted_values` on `type`
- Row count assertions (staging row count ≈ raw row count)
- `cited_by_count >= 0`
- `publication_year` between 1900 and current year

## BigQuery Design

- **Partitioning**: `publication_year` (integer range partitioning) — all three dashboard tiles filter/group by year
- **Clustering**: `subfield_id` — the primary analytical grouping dimension

## Dashboard Tiles

### Tile 1: The Takeover (temporal + categorical)
- **Type**: Stacked area chart or line chart
- **X**: publication_year
- **Y**: percentage share of CS works
- **Series**: AI vs non-AI (or top N subfields)
- **Satisfies**: "distribution of data across a temporal line"

### Tile 2: The Shelf Life (categorical comparison)
- **Type**: Grouped bar chart or heatmap
- **X**: subfield
- **Y**: median citation count at different age buckets (5yr, 10yr, 20yr)
- **Satisfies**: "distribution of some categorical data"
- **Caveat**: We approximate half-life from cumulative citations × years_since_publication, not from actual citation-over-time curves. Document this.

### Tile 3: The Winner's Game (temporal, stretch goal)
- **Type**: Line chart
- **X**: publication_year
- **Y**: Gini coefficient of cited_by_count
- **Series**: AI vs non-AI (or top N subfields)
- **Priority**: Build only after tiles 1 and 2 are solid. Drop if time is tight.

## Infrastructure

### Terraform
- GCS bucket (data lake)
- BigQuery dataset
- Service account with minimal permissions (storage admin, BQ data editor)
- Variables: project_id, region, bucket_name

### Docker
- Single Dockerfile for pipeline runtime (Python + dbt + Dagster)
- docker-compose.yml for local development (Dagster webserver + daemon)
- Streamlit may be a separate container or a simple `streamlit run` command

## Reproducibility Checklist

- [ ] `make setup` creates virtualenv, installs deps
- [ ] `make infra` runs Terraform
- [ ] `make ingest` runs OpenAlex CLI download + Parquet conversion
- [ ] `make upload` pushes Parquet to GCS
- [ ] `make transform` runs dbt
- [ ] `make dashboard` launches Streamlit
- [ ] `make all` runs full pipeline end-to-end
- [ ] README.md with clear setup instructions
- [ ] .env.example with all required variables documented

## Open Questions (resolve during development)

- Exact list of AI-related subfield IDs in OpenAlex topic taxonomy — needs exploration
- Whether to use BigQuery external tables (query Parquet in GCS directly) or load into native tables — external is simpler, native is faster. Try external first.
- Citation half-life methodology: cohort-based (group by publication year, compare cited_by_count distributions) is the most honest approach given the data. Document assumptions.
- Dagster + dbt integration: use `dagster-dbt` package for native asset mapping, or shell out to `dbt run`? Former is cleaner but adds complexity. Decide when wiring orchestration.
