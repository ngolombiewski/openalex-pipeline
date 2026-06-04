# Plan — Open Questions & Prospective Work

This file collects unresolved questions and items that are not yet part of the
project state. Remove an item once it is resolved and reflected in
`docs/architecture.md` or an ADR.

---

## Open Questions

### Data / Analysis

- **OpenAlex subfield IDs for AI** — The classification rule uses display names
  (`Artificial Intelligence`, `Computer Vision and Pattern Recognition`). The
  exact numeric subfield IDs need to be pinned via the API before the dbt
  staging models can filter on them reliably.
- **Citation half-life methodology** — Cohort-based approximation is the
  intended approach, but the exact assumptions need to be documented before
  implementation. The approximation relies on `counts_by_year`; document what
  "half-life" means in this context.

### Infrastructure

- **External vs. native BigQuery tables** — Try external tables (Parquet on
  GCS) first. Decide whether to switch to native BigQuery tables based on
  query performance and cost. A grounded cost/performance comparison is
  deferred; revisit when wiring the warehouse load.
- **`dagster-dbt` integration** — Native `dagster-dbt` integration vs.
  shelling out to dbt. Decide when wiring Dagster orchestration.
- **GCS path convention for bronze upload** — Provisional choice:
  `gs://{bucket}/bronze/publication_year={year}/{year}.parquet` (Hive-style
  partition layout, friendly to BigQuery external-table partition pruning).
  Confirm when the cloud lift happens.
- **GCS `_SUCCESS` marker** — Bronze uses Parquet presence as the completion
  signal locally. Whether GCS object semantics need an additional `_SUCCESS`
  marker (e.g. because of upload races, eventual consistency, or partial
  multi-object uploads) is unresolved. Extraction faced and rejected the
  analogous question for local disk; revisit specifically for GCS.

### Pipeline Boundaries

- **Deferred profiling pass** — Extraction deferred a full null-rate /
  filter-conformance scan over all records. Bronze is scoped as pure
  conversion and does *not* own it. Its home — a standalone profiling step or
  dbt staging tests — is undecided and must be assigned before silver.
- **Raw JSONL archival** — Decided: raw JSONL stays local, never uploads to
  GCS (it is a one-time intermediate consumed by bronze). Open sub-question:
  do we want a per-year tarball archive for reproducibility insurance, or
  rely on "extraction is re-runnable from OpenAlex"? No decision yet.

---

## Project Structure & Cloud Boundary — Settled

The following decisions are settled here and should be reflected in
`docs/architecture.md` (or a new ADR) before this section is removed.

### Tool composition

- **Terraform** provisions cloud infrastructure (GCS bucket, BigQuery dataset,
  IAM, service accounts). Runs out-of-band from data runs.
- **dbt** does transformation *inside the warehouse*: bronze Parquet is its
  input, silver and gold are dbt models. dbt does no extraction and no file
  movement.
- **Dagster** is the orchestrator: extraction and bronze become Dagster
  assets/ops; dbt models become Dagster assets via `dagster-dbt`. Dagster
  owns the DAG, the schedule, and retries.

### Repository layout

```
/data           local extract + bronze data; not committed
/docs           architecture, ADRs, data model
/src/openalex_pipeline/
    extraction/                 existing Python module
    bronze/                     new Python module (see Bronze Implementation below)
    orchestration/              Dagster definitions (later)
/dbt/                           self-contained dbt project
    dbt_project.yml
    profiles.yml                two targets: dev (DuckDB), prod (BigQuery)
    models/staging/             reads bronze
    models/silver/
    models/gold/
    macros/
/terraform/                     cloud infra
/tests                          pytest for Python modules
/scripts /notebooks             one-offs, exploration
```

### Silver and gold are dbt-only

No `src/openalex_pipeline/silver/` or `.../gold/`. Silver and gold are dbt
models under `/dbt/models/`. Bronze is the last Python package and the handoff
point between the Python pipeline and dbt.

### Local / cloud boundary

Decided: **upload bronze Parquet to GCS; do not lift extraction to cloud.**

- Extraction and bronze run locally. Extraction is a manual, daily,
  credit-limited pull against a third-party API — bottlenecked by OpenAlex's
  free tier, not compute — and is inherently a laptop-shaped job.
- Bronze's output Parquet uploads to GCS. BigQuery reads it (external tables
  first, per `SPECS.md`). dbt transforms inside BigQuery.
- This satisfies the project's "use cloud + a DWH" requirement: the data
  warehouse and modeling layer are cloud, the acquisition layer is local.
  This is a deliberate architectural boundary, not a cost workaround.

### dbt development

Earlier plans to develop dbt models locally with duckdb backend have been dropped:
After bronze, we move everything to the cloud already and develop there on a smaller
subset.
Reasoning: SQL dialects between DuckDB and BigQuery diverge and we don't want to duplicate
work unnecessarily.
