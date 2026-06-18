# openalex-pipeline

> **Status: work in progress.** Extraction and bronze run locally and are complete;
> bronze Parquet is in GCS behind a BigQuery external table. dbt staging, silver,
> gold, Dagster orchestration, and the dashboard are next.

An end-to-end batch data pipeline over the [OpenAlex](https://openalex.org/) corpus,
built to ask how AI has reshaped Computer Science research. It is a portfolio /
learning project: the pipeline and its infrastructure are as much the point as the
analysis they produce.

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

The decisions below are the ones a reviewer is most likely to want explained. Fuller
rationale lives in [`ARCHITECTURE.md`](ARCHITECTURE.md) and the per-layer design docs.

- **Local extraction + bronze, cloud from GCS onward.** The pull is bounded by
  OpenAlex's free-tier credits, not by compute — a laptop-shaped job that cloud would
  only complicate. The warehouse work (GCS + BigQuery + dbt) is where the project's
  weight deliberately sits. The boundary is a choice, not a cost workaround.

- **Filesystem as source of truth.** Pipeline state lives on disk: a per-year report
  signals extraction completion, the presence of `{year}.parquet` signals bronze. The
  manifest is *derived* and rebuilt wholesale each run. No separate state store.

- **Resumable extraction by construction, not by reconciliation.** The pull is a
  multi-day, credit-limited job sharded one calendar year at a time. The cursor for
  the *next* page is written before that page's file, and page writes always overwrite
  by number — so a crash costs exactly one re-fetched page on resume, with no staleness
  check or cleanup. Hitting the daily free-tier limit is a clean stop (typed, caught by
  the runner), not an error; the next day's run picks up where it left off.

- **Nested fields land as raw JSON strings in bronze.** The eight nested OpenAlex
  fields are stored verbatim, not as Parquet structs. Inferring structs and encoding
  them back fabricates explicit `null`s for keys a record never had; raw strings
  preserve source fidelity. dbt staging parses them once, into a native table.

- **`primary_topic` only for classification.** Simpler, avoids double-counting, and
  more defensible than second-guessing OpenAlex via the full topics array — a work's
  primary topic reflects its core contribution.

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

Each stage is a thin `python -m` module. Extraction is env-only; bronze and
upload take the data root from `OPENALEX_DATA_ROOT` (or explicit `--*-root` flags).

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
