# openalex-pipeline

> **Status:** the full data path is built and verified — extraction → bronze →
> GCS → BigQuery → dbt staging → silver → gold, with first-pass analytical
> results below. Next up: Dagster orchestration and a Streamlit dashboard.

An end-to-end batch data pipeline over the [OpenAlex](https://openalex.org/)
corpus, built to ask how AI has reshaped Computer Science research.

The data is the OpenAlex `works` entity filtered to Computer Science
(`primary_topic.field.id:17`), 1950–2026 — **14.78 M records** extracted,
**14.72 M** in the warehouse after documented quality filters, reconciled
against the ingestion manifest **to the exact row**.

## The questions

1. **The Takeover** — How has AI's share of CS research grown over time?
2. **The Shelf Life** — Do AI papers age faster? (citation half-life by subfield)
3. **The Winner's Game** — Is citation impact more concentrated in AI than in
   other CS subfields? (Gini coefficient)

AI is classified from a work's `primary_topic.subfield` under two variants —
`ai_strict` (Artificial Intelligence only) and `ai_broad` (+ Computer Vision
and Pattern Recognition) — and every result is reported for both. See
[`DATA_MODEL.md`](DATA_MODEL.md).

## First results

*First pass, computed in the gold layer over the full corpus; strict variant
quoted, broad tells the same story. Subject to refinement before the dashboard.*

**Q1 — The share of AI in CS is at an all-time high, but the path is not
monotone.** AI already held ~31% of CS output in 1980, bottomed near 23%
around 2012, and has climbed since — ~35% in 2025 and ~40% in the partial
2026 data. The dip-and-surge shape is consistent with the qualitative "AI
winters" narrative. (Caveat: OpenAlex assigns topics retroactively with a
modern taxonomy, which is what makes a 1980 "AI share" well-defined at all.)

**Q2 — No evidence so far that AI papers age faster.** Median citation
half-life (2012–2016 cohort, citation-weighted median age, linearly
interpolated) sits at ≈ 3.5 years for AI *and* for the rest of CS. An honest
null so far — interesting precisely because the "fast-moving field" intuition
predicts a gap.

**Q3 — Citation impact in AI is a winner's game, and more so than it first
looks.** Including all papers, every CS subfield is highly concentrated
(Gini 0.83–0.93) and AI sits mid-pack. But the all-papers Gini conflates two
things: how many papers are never cited, and how unequal the cited ones are.
Decomposing them flips the ranking —

| Subfield (top/bottom shown) | Uncited rate | Gini (all) | Gini (cited only) |
|---|---|---|---|
| **Artificial Intelligence** | 0.50 | 0.898 | **0.797** |
| **Computer Vision & PR** | 0.40 | 0.893 | **0.823** |
| Information Systems | 0.71 | 0.929 | 0.761 |
| Software | 0.58 | 0.877 | 0.712 |
| Hardware & Architecture | 0.42 | 0.826 | 0.701 |

AI and CV/PR have the *lowest* uncited rates in CS yet the *highest*
concentration among cited papers: AI papers get cited more often than average,
but the winnings pool at the top.

**Methodology notes.** OpenAlex's per-paper citation counts
(`counts_by_year`) cover a fixed 2012–2026 window (verified across all
cohorts), so Q2/Q3 are computed on a 2012–2016 publication cohort — the years
with full from-publication coverage and 10–14 years of follow-up. The cohort
also controls the age confound (older papers mechanically accumulate more
citations). Zero-citation papers are excluded from half-life (no half-life to
measure; reported as uncited-rate context) and included in the headline Gini
(the uncited majority *is* part of the concentration story).

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
Streamlit dashboard (next)
```

**Terraform** provisions the cloud infrastructure (GCS bucket, BigQuery
datasets, external table, service accounts + least-privilege IAM) out of band;
**Dagster** (next) will model every layer as a software-defined asset for
end-to-end lineage, with automation scoped to the cloud side — the local,
credit-limited pull stays a manually materialized asset.

## The warehouse

The dbt project (`dbt/`) models three layers on BigQuery, dev/prod split
across datasets, all rebuilt from the external table in one run:

- **staging** (`stg_works`) — parses the eight nested JSON columns landed
  verbatim in bronze, types the dates, applies the documented quality filters
  (retracted/paratext), dedups on `id`. Integer-range partitioned on
  `publication_year`, clustered on subfield — partition pruning verified via
  bytes-billed. Full-corpus row count reconciles against the bronze manifest
  exactly: `14,775,131 − 50,480 (retracted/paratext) − 1,282 (NULL status,
  documented drop) − 36 (dedup) = 14,723,333`.
- **silver** (`silver_works`) — one classified row per work: the
  `ai_strict`/`ai_broad` flags (pinned subfield ids as vars) plus the
  analytical column set. Row count == staging, asserted.
- **gold** — one question-shaped aggregate per analytical question, plus a
  per-paper half-life intermediate. Tiny tables, heavy tests: range bounds on
  every rate/share/Gini, uniqueness on every grain, and invariants like
  *strict ⊆ broad must survive aggregation* and *cited-only Gini ≤ all-papers
  Gini* pinned as data tests. 40+ tests, green on dev and prod.

Costs are engineered, not hoped for: a per-job `maximum_bytes_billed` cap,
physical (compressed) billing on the analytics datasets, and a canonical dev
slice (2012–2016, ~18% of the corpus) that doubles as the Q2/Q3 analytical
cohort, so dev gold previews prod numbers.

## Key design choices

Full rationale lives in [`ARCHITECTURE.md`](ARCHITECTURE.md) and the per-layer
design docs.

- **Local extraction + bronze, then cloud upload.** The extraction is bounded
  by the OpenAlex free credit limit, not compute — a laptop-shaped job. Data
  lands locally (~49 GB JSONL), compresses to Parquet (<5 GB), and uploads to
  GCS: the deliberate handoff point between the Python pipeline and the
  warehouse.
- **Resumable extraction by construction, not by reconciliation.** The pull is
  a multi-day, credit-limited job sharded one calendar year at a time. Hitting
  the daily free-tier limit is a clean stop; the next day's run picks up where
  it left off.
- **Filesystem as source of truth.** Pipeline state lives on disk; file
  presence and atomic rename (tmp → flush → fsync → rename) are the completion
  signals. The bronze manifest doubles as free analytics — corpus counts come
  from provenance files, not billed scans.
- **Corruption is loud.** Malformed JSONL, null primary keys, query-mix across
  a landing zone, and count mismatches all fail the affected unit immediately.
  Known failure modes get typed exceptions; unknown failures propagate
  untouched. No silent recovery.
- **Transformation belongs in the warehouse.** dbt does no extraction and no
  file movement — bronze Parquet (via the external table) is its input; silver
  and gold are dbt models. The external table is a pointer-with-schema, so it
  is Terraform's, not dbt's. There is no `silver/` or `gold/` Python package
  by design.

## Repository layout

```
src/openalex_pipeline/
    extraction/     OpenAlex API → paginated JSONL (cursor-based, resumable)
    bronze/         JSONL → Parquet (schema enforcement, manifest)
    upload/         bronze Parquet → GCS (idempotent, Hive-partitioned)
    orchestration/  Dagster definitions (next)
dbt/                staging → silver → gold models + tests
terraform/          GCS bucket, BigQuery datasets, external table, IAM
tests/              pytest for the Python modules
docs/               per-layer design docs and reference material
```

## Running locally

Requires Python ≥ 3.12 and [`uv`](https://docs.astral.sh/uv/). Configuration
is via environment variables; see [`.env.example`](.env.example).

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

# dbt — dev target builds the canonical 2012–2016 slice; prod the full corpus
uv run dbt build --project-dir dbt --vars '{year_min: 2012, year_max: 2016}'
uv run dbt build --project-dir dbt -t prod

# Tests (Python modules)
uv run pytest
```

## Docs

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — project overview, layer contracts, boundaries
- [`DATA_MODEL.md`](DATA_MODEL.md) — AI classification rules and the bronze schema
- [`STATE.md`](STATE.md) — current state of the build
- [`docs/`](docs/) — per-layer design docs
