# ARCHITECTURE.md

## Project

An end-to-end batch data pipeline over the OpenAlex corpus, built to explore
how AI research has changed Computer Science. The project is a learning vehicle:
the pipeline and its surrounding infrastructure matter as much as the analytical
output.

## Analytical Questions

The pipeline exists to answer three questions about AI's place in CS research:

1. **The Takeover** — How has AI's share of CS research grown over time?
2. **The Shelf Life** — Do AI papers age faster? (citation half-life by subfield)
3. **The Winner's Game** — Is citation impact more concentrated in AI than
   in other CS subfields? (Gini coefficient)

The classification has two variants (`ai_strict` and `ai_broad`); see
`DATA_MODEL.md`. Q1 is published for both variants. The current Q2/Q3 outputs
are subfield-grain comparisons carrying both classification flags; pooled
AI-vs-rest statistics are not yet implemented.

## Data Source

OpenAlex `works` entity, filtered to the Computer Science field
(`primary_topic.field.id:17`). The current corpus bounds are 1950–2026, with
roughly 14.8 M extracted records; the end year advances by an explicit annual
configuration change.

## Pipeline Shape

```
OpenAlex API
   │  (Python, daily pull)
   ▼
JSONL on local disk          ── extraction layer
   │  (Polars)
   ▼
Parquet on local disk        ── bronze layer
   │  (upload module)
   ▼
Parquet on GCS
   │  (BigQuery external tables)
   ▼
BigQuery raw                 ── dbt staging
   │  (dbt models)
   ▼
BigQuery silver              ── dbt models, AI classification and projection
   │  (dbt models)
   ▼
BigQuery gold                ── analytical aggregates, Q1/Q2/Q3
   │
   ▼
Streamlit dashboard (planned)
```

Dagster models the whole DAG as software-defined assets. The full historical
backfill remains manual, while the bounded current-year refresh is automated:
a daily local sweep, monthly invalidation of the current year, and a staleness
sensor that rebuilds the warehouse after GCS has converged. Terraform
provisions cloud infrastructure out of band.

### Layer contracts

These are the input/output surfaces between layers — what each layer hands the
next. Internal design is in the layer's own design doc.

| Layer | Input | Output | Location |
|---|---|---|---|
| Extraction | OpenAlex API | JSONL, one page-file per API page, sharded by `publication_year`. Year reports as completion signals. | Local: `${OPENALEX_DATA_DIR}/{year}/` |
| Bronze | Extraction JSONL | Parquet, one file per `publication_year` shard. Manifest with year-grained provenance. | Local: `${OPENALEX_DATA_ROOT}/bronze/{year}.parquet` |
| Bronze → GCS | Local bronze Parquet | Same Parquet, Hive-prefixed path for BigQuery partition pruning. | `gs://{bucket}/bronze/publication_year={year}/{year}.parquet` |
| dbt staging | BigQuery external tables over GCS Parquet | BigQuery tables; nested JSON strings parsed and flattened. | BigQuery dataset |
| dbt silver | dbt staging | BigQuery tables; AI classification applied, ablation variants computed. | BigQuery dataset |
| dbt gold | dbt silver | BigQuery tables; analytical aggregates for Q1/Q2/Q3. | BigQuery dataset |
| Streamlit (planned) | dbt gold | Web dashboard. | Cloud-hosted |

The eight nested OpenAlex fields are landed in bronze as **raw JSON strings**,
verbatim. dbt staging parses them. The choice and its rationale are in
`docs/design-archive/bronze-design.md`.

## Architectural Boundaries

### Local / cloud split

**Extraction and bronze run locally. Everything from GCS onward is cloud.**

- Extraction is an API-rate-limited, multi-day pull bounded by OpenAlex's free
  tier — bottlenecked by credits, not compute. It is a laptop-shaped job. No
  benefit from cloud compute and a real cost in complexity.
- Bronze runs locally because its input is the local JSONL. Its output —
  Parquet — is the cloud handoff point.
- The data warehouse and modeling layer are cloud (GCS + BigQuery + dbt),
  which satisfies the capstone's "use cloud + a DWH" requirement.

This boundary is deliberate, not a cost workaround. It places the heavy
infrastructure work where the project's evaluation actually weighs it (cloud
infra + IaC + warehouse modeling) while keeping the API-bound pull on the
machine that suits it.

### Path conventions across the boundary

Bronze writes flat locally (`{bronze_root}/{year}.parquet`) and uploads with a
Hive-style prefix added (`gs://{bucket}/bronze/publication_year={year}/{year}.parquet`).
The file is unchanged; only the path scheme differs. The Hive prefix exists
solely so BigQuery external tables can prune by partition.

### Raw JSONL stays local

Raw JSONL is a one-time intermediate, consumed by bronze and not promoted
further. It never uploads to GCS.

## Tool Composition

- **Terraform** provisions cloud infrastructure: GCS bucket, BigQuery
  dataset(s), service accounts, IAM. Runs out of band from data runs.
- **dbt** does transformation *inside the warehouse*: bronze Parquet (via
  BigQuery external tables) is its input; silver and gold are dbt models.
  dbt does no extraction and no file movement.
- **Dagster** is the orchestrator. Every layer is a software-defined asset —
  extraction, bronze, and upload directly, dbt models via `dagster-dbt` — so
  lineage is visible end to end. The expensive full historical pull stays a
  manual decision; the cheap, bounded current-year refresh is automated by the
  daily sweep + monthly invalidation + warehouse staleness sensor.

## Repository Layout

```
/                       AGENTS.md, ARCHITECTURE.md, STATE.md, DATA_MODEL.md
/docs                   active and archived design docs, reference material
/src/openalex_pipeline/
    extraction/         Python module — OpenAlex API → local JSONL
    bronze/             Python module — JSONL → Parquet
    upload/             Python module — bronze Parquet → GCS
    orchestration/      Dagster definitions, jobs, schedules, sensors
/dbt/                   self-contained dbt project
    dbt_project.yml
    profiles.yml        BigQuery target(s); dev = small dataset, prod = full
    models/staging/
    models/silver/
    models/gold/
    macros/
/terraform/             cloud infrastructure
/tests                  pytest for the Python modules
/scripts                one-offs, exploration
```

**Silver and gold are dbt-only.** There is no `src/openalex_pipeline/silver/`
or `.../gold/`. Bronze is the last Python *transformation* layer; upload only
moves its Parquet to GCS, the handoff point between the Python pipeline and dbt.

## Per-Layer Pointers

- **Extraction** — Python module at `src/openalex_pipeline/extraction/`.
  Design: `docs/design-archive/extraction-design.md`.
- **Bronze** — Python module at `src/openalex_pipeline/bronze/`. Design:
  `docs/design-archive/bronze-design.md`.
- **Upload** — Python module at `src/openalex_pipeline/upload/`. Design:
  `docs/design-archive/upload-design.md`.
- **dbt staging** — `dbt/models/staging/`. Archived design:
  `docs/design-archive/staging-design.md`.
- **dbt silver / gold** — `dbt/models/`. Archived designs:
  `docs/design-archive/silver-design.md` and
  `docs/design-archive/gold-design.md`.
- **Orchestration** — `src/openalex_pipeline/orchestration/` (Dagster).
  Design: `docs/orchestration-design.md`.
