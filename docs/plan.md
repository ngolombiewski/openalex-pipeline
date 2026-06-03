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

### Local dbt development

`dbt-duckdb` locally, `dbt-bigquery` in prod, two targets in `profiles.yml`.
`dbt-duckdb` can read bronze Parquet directly as external sources, which keeps
the bronze→staging handoff symmetric across local and cloud. Watch for SQL
dialect drift (date functions, struct/JSON access, `QUALIFY`); the three
analytical questions in `SPECS.md` use mostly vanilla aggregation, so drift
should be manageable.

### Small-files concern

Considered and dismissed for now. 75 year-files is not a small-files problem
(that would be 75,000). Per-year sharding is load-bearing — it is the
partition key in `DATA_MODEL.md` and the unit of idempotency in bronze — and
should not be collapsed for marginal storage-layout gains. The Hive-style GCS
path (above) gives BigQuery partition pruning without aggregation.

---

## Bronze Ingestion — Status

The bronze module's design is settled (see `docs/bronze-ingestion-design.md`)
and the implementation-uncertainty items below have been resolved by spike
(`scripts/bronze_ingest_spike.py`) against real production extract data. They
are kept here for one cycle as a record; remove this whole subsection once
the implementation lands.

### Resolved by spike

1. **Schema uniformity across years** — Sampled first-page schemas were
   uniform across multiple years, but this is mild evidence only (long-tail
   sparse records cluster in later pages). The forced explicit schema is
   load-bearing regardless and is the chosen approach.
2. **`scan_ndjson` forced-schema behavior** — Confirmed that forcing nested
   fields to `pl.String` yields raw verbatim JSON (Polars does not parse them
   into structs). The full 21-column mixed schema collects cleanly over full
   years and concatenates across years. The previously considered alternative
   — infer structs then `struct.json_encode()` back to String — is rejected
   on fidelity grounds: `struct.json_encode()` materializes schema-null keys
   that were absent in the source.
3. **Zero-byte page file** — Polars `scan_ndjson` *fails* on a zero-byte
   file, contrary to the original assumption. Bronze handles this by
   detecting the case before any read and writing an empty Parquet typed by
   `BRONZE_SCHEMA`.
4. **Scalar coercion under forced schema** — Confirmed `scan_ndjson` raises
   `ComputeError` on a scalar that does not match its forced dtype (it does
   *not* silently coerce to null). The forced schema therefore doubles as
   scalar type-conformance validation at read time.
5. **Skip rule granularity** — Settled: skip on Parquet presence alone. No
   mtime comparison. To force re-ingestion, delete the year's Parquet. This
   mirrors extraction's stance on external tampering.
6. **Manifest column set** — Settled: see `docs/bronze-ingestion-design.md`.
   `ingested_at` is the Parquet file's mtime, not the manifest rebuild
   timestamp, so re-running does not re-stamp already-ingested years.

### Open data-model contradiction

- **`docs/DATA_MODEL.md` specifies a per-record `_extracted_at` column.**
  Bronze adds *no* per-record provenance columns — all provenance lives in
  the manifest at year granularity. Until `DATA_MODEL.md` is updated, the
  data model and bronze's output disagree. This must be fixed before the
  bronze implementation is merged.

---

## Bronze Implementation — Sequence

Mirroring the extraction module's build sequence:

1. **Contracts** — function/class headers and docstrings. (Done — see
   `bronze.py` in outputs; to be split into the package below before
   landing.)
2. **Design + write tests against contracts.** (Next.)
3. **Implement** by harvesting the spike's verified read path
   (`scripts/bronze_ingest_spike.py`) into the module, with a cleanup pass
   for the spike's exploratory-code quality (broad `except`s, `# noqa`s).

### Module split

`src/openalex_pipeline/bronze/`:

- `schema.py` — `BRONZE_SCHEMA`, `NESTED_COLUMNS`. Pure data, no internal
  dependencies.
- `errors.py` — `BronzeError`, `CorruptedState`, `IntegrityError`.
- `core.py` — `YearState`, `classify_year`, `YearIngestResult`,
  `ingest_year`, `write_empty_year`. The ingestion work.
- `manifest.py` — `build_manifest`, `write_manifest`. Derived state,
  separated from `core.py` to keep that distinction structural.
- `runner.py` — `run`. Loops, delegates, aggregates.
- `__main__.py` — `resolve_roots`, `build_years_list`, `parse_args`, `main`.
  CLI only.

Dependency direction (a clean DAG, no cycles): `schema` and `errors` are
leaves; `core` imports both; `manifest` imports `schema` and `errors`;
`runner` imports `core` and `manifest`; `__main__` imports `runner`.

### CLI conventions

- Invocation: `python -m openalex_pipeline.bronze`.
- Single env var: `OPENALEX_DATA_ROOT`. Extraction and bronze both derive
  their directories from it (`{root}/extract`, `{root}/bronze`). CLI flags
  `--extract-root` and `--bronze-root` override.
- `--years START:END` for an explicit inclusive range, or omitted to
  discover and ingest every extraction-complete year found under
  `extract_root`. The two modes give the manifest different coverage by
  design (explicit range = bounded universe; default = whatever exists).
- Note: the env var change makes the existing extraction module's
  `OPENALEX_DATA_DIR` redundant. Extraction should be updated to read
  `OPENALEX_DATA_ROOT` and append `/extract` itself, so both modules share
  a single root variable.
