# openalex-pipeline

> **Status: work in progress.** Extraction and bronze run locally and are complete;
> bronze Parquet is in GCS behind a BigQuery external table. dbt staging, silver,
> gold, Dagster orchestration, and the dashboard are next.

An end-to-end batch data pipeline over the [OpenAlex](https://openalex.org/) corpus,
built to ask how AI has reshaped Computer Science research.

The data is the OpenAlex `works` entity filtered to Computer Science
(`primary_topic.field.id:17`), 1950 to present — roughly **14.7 M records**.

## The questions

1. **The Takeover** — How has AI's share of CS research grown over time?
2. **The Shelf Life** — Do AI papers age faster? (citation half-life by subfield)
3. **The Winner's Game** — Is citation impact more concentrated in AI than in other
   CS subfields? (Gini coefficient)

AI is classified from a work's `primary_topic.subfield` and computed under two
variants — `ai_strict` (Artificial Intelligence only) and `ai_broad` (+ Computer
Vision and Pattern Recognition). All three questions are reported for both. See
[`DATA_MODEL.md`](DATA_MODEL.md).

## Pipeline

```
OpenAlex API
   │  Python, API-rate-limited daily pull
   ▼
JSONL on local disk        ─ extraction
   │  Polars, format conversion only
   ▼
Parquet on local disk      ─ bronze
   │  upload, idempotent, Hive-partitioned path
   ▼
Parquet in GCS
   │  BigQuery external table
   ▼
BigQuery raw → staging → silver → gold   ─ dbt
   │  parse/flatten → AI classification → analytical aggregates
   ▼
Streamlit dashboard
```

**Dagster** orchestrates the DAG as software-defined assets; **Terraform** provisions
the cloud infrastructure out of band.

## Key design choices

Full rationale lives in [`ARCHITECTURE.md`](ARCHITECTURE.md) and the per-layer design docs.

- **Local extraction + bronze, then cloud upload.** The fundamental constraint on the
extraction is the OpenAlex free credit limit. In order to minimize cloud expenses, we
land the data locally (~49 GB) and compress to parquet (<5 GB), then upload to a GCS
bucket.

- **Resumable extraction by construction, not by reconciliation.** The pull is a
  multi-day, credit-limited job sharded one calendar year at a time. Hitting the daily
  free-tier limit is a clean stop; the next day's run picks up where it left off.

- **Filesystem as source of truth.** Pipeline state lives on disk. Atomic write pattern
(tmp -> flush -> fsync -> rename) is employed throughout extraction.

- **Corruption is loud.** Malformed JSONL, null primary keys, query-mix across a
  landing zone, and count mismatches all fail the affected unit immediately. Known
  failure modes get typed exceptions; unknown failures propagate untouched. No silent
  recovery.

- **Transformation belongs in the warehouse.** dbt does no extraction and no file
  movement — bronze Parquet (via the external table) is its input, silver and gold are
  dbt models. The external table is a pointer-with-schema, so it is Terraform's, not
  dbt's. There is no `silver/` or `gold/` Python package by design.

## Repository layout

```
src/openalex_pipeline/
    extraction/     OpenAlex API → paginated JSONL (cursor-based, resumable)
    bronze/         JSONL → Parquet (schema enforcement, manifest)
    upload/         bronze Parquet → GCS (idempotent, Hive-partitioned)
    orchestration/  Dagster definitions (later)
dbt/                staging → silver → gold (in progress)
terraform/          GCS bucket, BigQuery datasets, external table, IAM
tests/              pytest for the Python modules
docs/               per-layer design docs and reference material
```

## Running locally

Requires Python ≥ 3.12 and [`uv`](https://docs.astral.sh/uv/). Configuration is via
environment variables; see [`.env.example`](.env.example).

Each stage is a thin module. Extraction is env-only; bronze and upload take the data
root from `OPENALEX_DATA_ROOT` (or explicit `--*-root` flags).

```bash
uv sync

# Extraction — env-configured (multi-day, rate-limited pull)
uv run -m openalex_pipeline.extraction

# Bronze — convert completed extraction years to Parquet (all years by default)
uv run -m openalex_pipeline.bronze
# …or a specific inclusive range
uv run -m openalex_pipeline.bronze --years 2000:2024

# Upload — push bronze Parquet to GCS, Hive-partitioned for BigQuery
uv run -m openalex_pipeline.upload --bucket "$OPENALEX_GCS_BUCKET"

# Tests
uv run pytest
```

## Docs

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — project overview, layer contracts, boundaries
- [`DATA_MODEL.md`](DATA_MODEL.md) — AI classification rules and the bronze schema
- [`STATE.md`](STATE.md) — current state of the build
- [`docs/`](docs/) — per-layer design docs
</content>
</invoke>
