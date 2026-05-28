# openalex-pipeline

> **Work in progress.** Extraction and bronze ingestion are complete. dbt modelling and the cloud lift are underway.

End-to-end batch data pipeline for analysing AI's growth and impact within computer science research. Data source: [OpenAlex](https://openalex.org/) works entity (~14.7 M CS works, 1950–present). DE Zoomcamp capstone project.

## Analytical questions

1. **The Takeover** — How has AI's share of CS research grown over time?
2. **The Shelf Life** — Do AI papers age faster? (citation half-life by subfield)
3. **The Winner's Game** — Is citation impact more concentrated in AI than other CS subfields? (Gini coefficient)

AI classification uses `primary_topic.subfield` from OpenAlex. Two variants are computed: `ai_strict` (Artificial Intelligence only) and `ai_broad` (+ Computer Vision and Pattern Recognition). See `DATA_MODEL.md` for details.

## Pipeline

```
OpenAlex API
    └─ extraction (CLI, paginated cursor)
         └─ JSONL page files  →  bronze ingestion (Polars)
              └─ Parquet shards (per year)  →  GCS
                   └─ BigQuery (external tables → native)
                        └─ dbt (staging → silver → marts)
                             └─ Streamlit dashboard
```

Orchestrated by **Dagster** (software-defined assets). Cloud infra via **Terraform**.

## Status

| Stage | Status |
|---|---|
| Extraction | ✅ Done — `src/openalex_pipeline/extraction/`, tests in `tests/extraction/` |
| Bronze ingestion | ✅ Done — `src/openalex_pipeline/bronze/`, tests in `tests/bronze/` |
| dbt models (local / DuckDB) | 🔄 In progress |
| GCS upload | 🔄 In progress (parallel to dbt local work) |
| BigQuery + dbt silver | ⬜ Queued |
| Dagster orchestration | ⬜ Queued |
| Streamlit dashboard | ⬜ Queued |

## Repository layout

```
src/openalex_pipeline/
    extraction/     # OpenAlex API → paginated JSONL (cursor-based)
    bronze/         # JSONL → Parquet (schema enforcement, manifest)

tests/
    extraction/
    bronze/

dbt/                # staging → silver → marts (in progress)
terraform/          # GCS bucket, BigQuery dataset, service accounts
```

## Data layers

**Extract** — raw JSONL page files, one directory per year. Extraction is resumable; `_YEAR_REPORT.json` is the completion signal per year.

**Bronze** — one Parquet file per year, explicit 21-column schema, nested fields as raw JSON strings. A `_MANIFEST.parquet` tracks counts, mismatch flags, and ingestion timestamps at year granularity. Bronze is a thin format conversion: no flattening, no deduplication, no per-record provenance columns.

**Silver** (planned) — dbt staging models parse and flatten nested JSON fields; dbt silver models apply quality filters (`is_retracted`, `is_paratext`) and compute `is_ai` / `ai_strict` / `ai_broad` flags.

**Marts** (planned) — pre-aggregated tables for the three analytical questions above, consumed by Streamlit.

## Local development

```bash
# Install (requires Python ≥ 3.11)
pip install -e ".[dev]"

# Extraction
openalex-extract --start-year 2000 --end-year 2024

# Bronze ingestion
openalex-ingest --start-year 2000 --end-year 2024

# Tests
pytest tests/
```

Configuration is via environment variables (`OPENALEX_DATA_DIR`, `OPENALEX_BRONZE_DIR`, `OPENALEX_START_YEAR`, `OPENALEX_END_YEAR`); CLI flags override env vars for bronze.

## Key design decisions

- **Primary topic only** for AI classification — avoids double-counting; rationale in `DATA_MODEL.md`.
- **Nested fields as raw JSON strings in bronze** — schema stability across years; Polars `forced-String` on read preserves source fidelity (struct-encode rejected: it fabricates `null` keys absent from source).
- **Completion signals on disk, not in a database** — `_YEAR_REPORT.json` for extraction, `{year}.parquet` presence for bronze; manifest is derived and rebuilt wholesale each run.
- **Corruption is loud** — malformed JSONL, null primary keys, and scalar type mismatches all fail the affected year immediately; no silent recovery.

## Docs

- [`SPECS.md`](SPECS.md) — analytical questions, pipeline shape, open questions
- [`DATA_MODEL.md`](DATA_MODEL.md) — AI classification rules, bronze schema
- [`docs/extraction-module-design.md`](docs/extraction-module-design.md) — extraction contracts and invariants
- [`docs/ingestion-design.md`](docs/ingestion-design.md) — bronze ingestion contracts and invariants