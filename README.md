# openalex-pipeline

> **Status:** the full data path is built and verified — extraction → bronze →
> GCS → BigQuery → dbt staging → silver → gold. Dagster orchestration is
> complete. Q2's annual citation-age replacement is implemented and verified
> locally; dev/prod deployment and reconciliation are pending. Q3's pooled
> comparison, Streamlit, and closeout remain.

An end-to-end batch data pipeline over the [OpenAlex](https://openalex.org/)
corpus, built to ask how AI has reshaped Computer Science research.

The data is the OpenAlex `works` entity filtered to Computer Science
(`primary_topic.field.id:17`), 1950–2026 — **14.78 M records** extracted,
**14.72 M** in the warehouse after documented quality filters, reconciled
against the ingestion manifest **to the exact row**.

## The questions

1. **The Takeover** — How has AI's share of CS research grown over time?
2. **The Shelf Life** — How does the age of cited literature differ among AI,
   CV/PR, and the rest of CS, and how has that changed over time? (annual
   citation age)
3. **The Winner's Game** — Is citation impact more concentrated in AI than in
   other CS subfields? (Gini coefficient)

Two pinned `primary_topic.subfield` ids identify Artificial Intelligence and
Computer Vision and Pattern Recognition. Q1 reports strict AI and broad
AI-plus-CV/PR variants. Q2 instead uses the more informative mutually exclusive
AI, CV/PR, and rest-of-CS partition. Q3 currently publishes subfield rows
carrying both classification flags. See [`DATA_MODEL.md`](DATA_MODEL.md).

## First results

*Validated prod findings for Q1 and the current Q3 subfield view. Q2 results
will be published only after the approved annual citation-age specification is
implemented and reconciled.*

**Q1 — The share of AI in CS is at an all-time high, but the path is not
monotone.** AI already held ~31% of CS output in 1980, bottomed near 23%
around 2012, and has climbed since — ~35% in 2025 and ~40% in the partial
2026 data. The dip-and-surge shape is consistent with the qualitative "AI
winters" narrative. (Caveat: OpenAlex assigns topics retroactively with a
modern taxonomy, which is what makes a 1980 "AI share" well-defined at all.)

**Q2 — Annual citation age, results pending.** The decided replacement will
measure the citation-weighted median age of cited AI, CV/PR, and rest-of-CS
works in each year from 2012 through 2025. It is explicitly a full-corpus
snapshot, not a live current-year metric. See
[`docs/gold-revisit-design.md`](docs/gold-revisit-design.md).

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

**Methodology notes.** Q2 will use OpenAlex's year-resolved citation counts
(`counts_by_year`) across the full cited-work corpus and classify the cited
work, not the unknown citing work. Q3 uses the age-controlled 2012–2016
publication cohort so older papers do not mechanically dominate cumulative
citation totals. Zero-citation papers are included in the headline Gini: the
uncited majority is part of the concentration story.

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
**Dagster** models every layer as a software-defined asset for end-to-end
lineage. The full historical pull stays manual; the bounded current-year
refresh and warehouse rebuild are automated by a daily sweep, monthly
invalidation, and staleness sensor.

Starting Dagster starts the production automation: both schedules and the
warehouse sensor default to running. Run Dagster only from a direnv-active
shell. After changing `.envrc`, run `direnv allow`; after clearing the
advisory `.dagster/` state directory, run `direnv reload` before restart so
the absolute instance directory and canonical config link are recreated.

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
- **gold** — question-shaped analytical aggregates. Q1 and the current Q3
  subfield view are deployed and validated. The approved
  `gold_citation_age_by_year` Q2 replacement is implemented and verified
  locally, with deployment pending. Model grains, ranges, classification
  partitions, and analytical invariants are pinned as dbt tests.

Costs are engineered, not hoped for: a per-job `maximum_bytes_billed` cap,
physical (compressed) billing on the analytics datasets, and a canonical dev
slice (2012–2016, ~18% of the corpus) matching the Q3 analytical cohort. It is
a structural development target for Q2; only the full prod corpus yields
representative Q2 citation-age values.

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
    orchestration/  Dagster definitions, jobs, schedules, sensors
dbt/                staging → silver → gold models + tests
terraform/          GCS bucket, BigQuery datasets, external table, IAM
tests/              pytest for the Python modules
docs/               per-layer design docs and reference material
```

## Running locally

Requires Python ≥ 3.12 and [`uv`](https://docs.astral.sh/uv/). Configuration
is via environment variables; see [`.env.example`](.env.example).
`OPENALEX_DATA_ROOT` is the single local data root: extraction uses its
`extract/` child, bronze uses `bronze/`, and orchestration keeps its lock at the
root. The bronze and upload path flags remain explicit overrides for one-off
operations.

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
- [`docs/gold-revisit-design.md`](docs/gold-revisit-design.md) — approved Q2 implementation contract
- [`docs/`](docs/) — per-layer design docs
