# openalex-pipeline

> **Status:** the full data path is built and verified — extraction → bronze →
> GCS → BigQuery → dbt staging → silver → gold. Dagster orchestration is
> complete. All three analytical questions are deployed and prod-reconciled.
> Streamlit and closeout remain.

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
AI, CV/PR, and rest-of-CS partition. Q3 publishes subfield rows carrying both
classification flags as its primary view, plus a secondary pooled relation
using the same exclusive partition. See [`DATA_MODEL.md`](DATA_MODEL.md).

## First results

*Validated prod findings for all three questions.*

**Q1 — The share of AI in CS is at an all-time high, but the path is not
monotone.** AI already held ~31% of CS output in 1980, bottomed near 23%
around 2012, and has climbed since — ~35% in 2025 and ~40% in the partial
2026 data. The dip-and-surge shape is consistent with the qualitative "AI
winters" narrative. (Caveat: OpenAlex assigns topics retroactively with a
modern taxonomy, which is what makes a 1980 "AI share" well-defined at all.)

**Q2 — Citation attention has shifted toward younger work across CS, with
CV/PR generally the most recent.** Median citation age falls from 8 to 5 years
for AI, from 7 to 5 for CV/PR, and from 7 to 5 for the rest of CS between 2012
and 2025. By 2025, 55.4% of AI citations, 57.2% of CV/PR citations, and 54.3%
of rest-of-CS citations go to works at most five years old. These are
citation-weighted ages of cited works, not evidence about what AI-authored
papers cite or proof of faster intrinsic obsolescence. Q2 is a full-corpus
snapshot through citation year 2025, not a live current-year metric. See
[`docs/gold-q2-revisit-design.md`](docs/gold-q2-revisit-design.md).

**Q3 — Citation impact in AI is a winner's game, and more so than it first
looks.** Measured over the five complete calendar years after publication, the
2020 cohort shows every CS subfield highly concentrated on the all-papers Gini
(0.81–0.92), with AI 4th of 11. But that number conflates two things: how many
papers are never cited, and how unequal the cited ones are. Decomposing them
reorders the field —

| Subfield (selected) | Uncited rate | Gini (all) | Gini (cited only) |
|---|---|---|---|
| **Artificial Intelligence** | 0.46 | 0.871 | **0.760** |
| Computer Graphics & CAD | 0.68 | 0.922 | 0.759 |
| **Computer Vision & PR** | 0.35 | 0.839 | **0.751** |
| Information Systems | 0.62 | 0.898 | 0.729 |
| Software | 0.61 | 0.864 | 0.651 |
| Hardware & Architecture | 0.47 | 0.810 | 0.639 |

AI has the highest cited-only Gini in CS and CV/PR the third, but what sets
them apart is the pairing: both combine that concentration with among the
*lowest* uncited rates in the field. AI papers get cited more often than
average, and the winnings still pool at the top. The contrast is Computer
Graphics, whose near-identical cited-only Gini comes with more than twice the
uncited rate, and Information Systems, which tops the all-papers Gini purely
because 62% of its papers are never cited at all.

The cohort axis shows this hardening over time. Across publication cohorts
2012 → 2020 at the same five-year window, AI's Gini among cited papers rises
0.684 → 0.760 while its uncited rate falls 0.576 → 0.464. More AI papers get
cited than ever, and the citations they attract are more unequally distributed
than ever.

One caveat worth stating plainly: on the *pooled* AI-versus-rest-of-CS view,
AI is **not** more concentrated overall — the all-papers Gini gap runs
slightly in the other direction for most cohorts. AI's distinctiveness is the
low uncited rate combined with high concentration among the cited, not a
higher headline Gini.

**Methodology notes.** Q2 uses OpenAlex's year-resolved citation counts
(`counts_by_year`) across the full cited-work corpus and classifies the cited
work, not the unknown citing work. Q3 replaces cumulative citation counts with
a **fixed window**: citations received in the first N complete calendar years
after the publication year, so cohorts are compared on equal exposure rather
than on elapsed time. The publication year is excluded from the window because
its length depends on publication month; including it moves every Gini by less
than 0.011 and changes no ranking. Zero-citation papers are included in the
headline Gini — the uncited majority is part of the concentration story — and
`gini_cited_only` separates the two effects. Cells whose window ends in 2025
rest on the least-settled citation year in the snapshot.

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
- **gold** — question-shaped analytical aggregates, all deployed and
  reconciled: Q1; `gold_citation_age_by_year` over citation years 2012–2025;
  and Q3's `gold_citation_gini_by_subfield` plus the pooled
  `gold_citation_gini_by_group` over publication cohorts 2012–2024. Model
  grains, ranges, classification partitions, and analytical invariants are
  pinned as dbt tests.

Costs are engineered, not hoped for: a per-job `maximum_bytes_billed` cap,
physical (compressed) billing on the analytics datasets, and a canonical dev
slice (2012–2016, ~18% of the corpus) overlapping the first five Q3 cohorts.
It is an analytically faithful Q3 preview for those cohorts but not a
byte-for-byte one, and only a structural target for Q2; only the full prod
corpus yields representative Q2 citation-age values.

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
- [`docs/gold-q2-revisit-design.md`](docs/gold-q2-revisit-design.md) — approved Q2 implementation contract
- [`docs/gold-q3-revisit-design.md`](docs/gold-q3-revisit-design.md) — approved Q3 implementation contract
- [`docs/`](docs/) — per-layer design docs
