# OVERVIEW

> **Derived from `be6d94a` (2026-07-31).** Regenerate if `git log be6d94a..HEAD`
> touches `src/`, `dbt/`, or `terraform/`; treat as stale until then. Update
> this line whenever the file is regenerated.

Architectural orientation for the `openalex-pipeline` repository. Derived from
executable contents (`src/`, `dbt/`, `terraform/`, `tests/`). It is a map, not a
specification — use it to decide what to read next.

**This file is regenerated from source, not maintained.** It is authoritative
for nothing; the code is. Prefer regenerating it over patching it.

## 1. What the system does

It extracts the OpenAlex **Computer Science works** corpus (server-side filter,
`primary_topic.field.id:17`), lands it locally, ships it to GCS, and builds
three question-shaped BigQuery aggregates via dbt:

<!-- prettier-ignore -->
| Question | Gold model | Grain |
| --- | --- | --- |
| Q1 AI's share of CS works | `gold_ai_share_by_year` | `publication_year × variant(strict\|broad)` |
| Q2 Citation-weighted age of cited works | `gold_citation_age_by_year` | `citation_year × cited_group(ai\|cv_pr\|rest_cs)` |
| Q3 Citation concentration (Gini/top-k) | `gold_citation_gini_by_subfield` (primary), `gold_citation_gini_by_group` (secondary) | `subfield_id \| cited_group × publication_year × citation_age` |

"AI" is pinned by **stable OpenAlex subfield id**, never display name:
`ai_strict` = subfield 1702; `ai_broad` = 1702 + 1707 (CV/PR). This ablation
pair is a load-bearing contract that runs from `dbt_project.yml` vars through
silver into every gold model.

## 2. Data flow

```
OpenAlex API
  │  extraction/    (Python; per-year shard dirs of JSONL pages + cursor)
  ▼  {DATA_ROOT}/extract/{year}/{_META,_CURSOR,page-NNNN.jsonl,_YEAR_REPORT}
bronze/            (Python; JSONL -> one Parquet per year, 21 pinned columns)
  ▼  {DATA_ROOT}/bronze/{year}.parquet  +  _MANIFEST.parquet
upload/            (Python; mtime-vs-blob skip logic)
  ▼  gs://openalex-pipeline-bronze/bronze/publication_year={year}/...
     gs://.../upload/_MANIFEST.parquet   (deliberately OUTSIDE the hive tree)
BigQuery external table  openalex_raw.bronze_external   (Terraform-owned)
  ▼
dbt: stg_works -> silver_works -> gold_*   (dataset openalex_analytics[_dev])
```

Orchestrated end-to-end by **Dagster** (`orchestration/definitions.py`), but
every Python stage also has a standalone CLI
(`python -m openalex_pipeline.{extraction,bronze,upload}`).

## 3. Responsibility boundaries

Each package is layered leaf → composite, and the layering is enforced by import
discipline that the module docstrings state explicitly. **Preserve it.**

### `extraction/` — API → JSONL

- `settings.py` — the _only_ holder of runtime config (env, `OPENALEX_*`
  prefix).
- `connector.py` — the single HTTP call + all retry/backoff. Injected into the
  worker as a callable; the primary test seam (no network in tests).
- `storage.py` — _all_ filesystem I/O. Five-function contract: `classify_year`,
  `initialize_year`, `write_page`, `finalize_year`, `read_year_report`. Enforces
  atomic durable writes, immutability of `_META.json`/`_YEAR_REPORT.json`.
- `worker.py` — pure state machine over one year; the pagination loop is
  **pinned** in the docstring (fresh path is
  `fetch_page → initialize_year → write_page`, so a first-fetch failure leaves
  nothing on disk).
- `runner.py` — owns the **canonical query string** (parameter/filter order);
  pure orchestration, no I/O.
- `exceptions.py` — two base classes (`ConnectorError`, `StorageError`).
  `DailyLimitReached` (429) is an _expected clean stop_, not an error.

### `bronze/` — JSONL → Parquet

- `schema.py` (leaf) — the 21-column `BRONZE_SCHEMA`, imposed on read, never
  inferred. Eight nested columns stay **raw JSON strings**; dates stay strings.
  Scalar dtypes are the integrity check (non-conforming value → ComputeError).
- `core.py` — year classification (`INGESTED/READY/PENDING`), corpus-level query
  homogeneity assertion, single-year ingest.
- `manifest.py` — derived, never authoritative; rebuilt wholesale from disk and
  deliberately _does not_ reuse `core.classify_year`.
- `runner.py` — the only module touching both core and manifest.

### `upload/` — Parquet → GCS

Same core/manifest/runner shape. The `Bucket` is **injected**, never constructed
in `core.py` — one mockable cloud seam.

### `orchestration/` — Dagster

- `config.py` — resolves existing env vars into `OrchestrationConfig`; adds no
  new config layer (runners keep owning their own config).
- `convergence.py` — pure predicates, **no Dagster imports, no writes**. Cloud
  metadata is passed in by the caller so it stays unit-testable.
- `cloud.py` — the GCS/BigQuery metadata calls the predicates consume.
- `lock.py` — `flock` on `{DATA_ROOT}/.orchestration.lock`. Writers take
  `LOCK_EX` (block); the sensor takes `LOCK_SH|LOCK_NB` and skips if a writer
  holds it.
- `invalidate.py` — durable tombstone request/execute protocol for refreshing
  the in-flight current year.
- `dbt_prep.py` — parses a current **prod-target** dbt manifest at import time.
- `definitions.py` — assets, jobs, schedules, sensor.

### `dbt/` — warehouse

- `staging/stg_works.sql` — does exactly four things: parse the 8 JSON columns,
  type the 2 date columns, apply hygiene filters (`is_retracted = false`,
  `is_paratext = false`, year bounds), dedup on `id` via QUALIFY. No
  classification, no aggregation.
- `silver/silver_works.sql` — classification (`is_ai_strict`/`is_ai_broad`) +
  projection. Same grain as staging, no filter.
- `gold/*` — question-shaped aggregates only.
- `macros/q3_paper_windows.sql` — shared cumulative fixed-window expansion used
  by _both_ Q3 models, so subfield and group grains stay reconcilable.

## 4. Contracts between components

- **Canonical query string** (`extraction/runner.canonical_query`) is the
  identity of a year shard. It is written to `_META.json`, re-verified on resume
  (`QueryMismatch`), asserted homogeneous across the corpus by bronze, and
  recomputed by the convergence predicate. Changing its shape invalidates
  on-disk state. The API key is deliberately _not_ part of query identity and is
  never persisted.
- **Year-shard state machine**: `FRESH → IN_PROGRESS → COMPLETE`; presence of
  `_YEAR_REPORT.json` means complete. Any other file combination →
  `CorruptedState`, never silent recovery.
- **21-column bronze schema** is declared twice and consumed a third time:
  `bronze/schema.py` (imposed on write), `terraform/bigquery.tf` (pinned
  external-table schema, read by BigQuery), and
  `dbt/models/staging/stg_works.sql` (consumed by name). `publication_year`
  comes from the Hive partition key and must **not** appear in the Terraform
  schema list. The two _declarations_ are the pair that can drift silently, and
  `tests/bronze/test_schema_mirror.py` asserts they agree on names, order,
  types, and nullability. The dbt leg is self-checking — it fails loudly at
  build time against the real external table. `extraction/runner.SELECT_COLUMNS`
  is a fourth copy of the column list, requested server-side; it is not covered
  by that test.
- **Manifests are derived, never authoritative.** Bronze `_MANIFEST.parquet` and
  the GCS `upload/_MANIFEST.parquet` are rebuilt wholesale each run. The upload
  manifest is the _only_ one read back (by the staleness sensor).
- **Bronze count invariant**: `records_fetched == bronze_row_count` per ingested
  year, re-asserted on every manifest rebuild (`IntegrityError`).
- **Upload skip rule**: skip iff blob exists and `blob.updated >= local mtime`.
  The same `should_skip` function is reused by `convergence.is_converged`.
- **dbt asset wiring**: `OpenAlexDbtTranslator` remaps the dbt source
  `bronze.bronze_external` to the Dagster asset key `bronze_gcs`, which is what
  joins the Python chain to the dbt graph. Breaking that mapping severs the
  graph.
- **Materializations** are restricted to `table`/`view`; anything else raises
  `UnsupportedDbtMaterialization` from `dbt_model_relations`.
- **`gold_citation_age_by_year` has an enforced dbt contract** (`_gold.yml`) —
  its column types are a hard interface.

## 5. Execution and verification

**Environment.** `direnv` (`.envrc`) loads `.env` and points `DAGSTER_HOME` at
`.dagster/`, symlinking the tracked root `dagster.yaml`. Python is managed by
`uv` (3.12+). GCP auth is **ADC impersonating `dbt-runner@…`** — no key files
anywhere.

**Run it.**

```
python -m openalex_pipeline.extraction        # API -> JSONL (resumable, daily-limit aware)
python -m openalex_pipeline.bronze            # JSONL -> Parquet + manifest
python -m openalex_pipeline.upload            # Parquet -> GCS + manifest
dbt build --project-dir dbt                   # target defaults to dev
dagster dev                                   # full orchestration UI
```

**Dagster topology** (`definitions.py`):

- assets `extracted_jsonl → bronze_parquet → bronze_gcs → openalex_dbt_assets`
- job `local_sweep` (first three assets) — daily cron `0 4 * * *` Europe/Berlin
- job `invalidate_refresh_year` — monthly `0 3 1 * *`, tombstones the current
  year
- job `warehouse_build` (dbt assets), triggered _only_ by
  `warehouse_staleness_sensor` (≥4h interval): skips if a build is in flight, if
  the local lock is held, if local/GCS is not converged, or if the warehouse is
  fresh. Run key is the latest upload timestamp; `dagster/max_retries: 3`.

**Testing.** 255 pytest tests under `tests/`, mirroring package structure. No
network and no cloud: the connector callable and the GCS `Bucket` are injected
seams; `responses` and `freezegun` are dev deps.
`tests/bronze/test_schema_mirror.py` is the one test that reads outside `src/` —
it parses `terraform/bigquery.tf`. dbt verification is substantial — 25 singular
tests in `dbt/tests/` (reconciliation, ordering, cohort floors, cross-grain
agreement) plus schema tests in `_gold.yml`/`_silver.yml`. Lint/type: `ruff`,
`pyright`.

**Cost guards** worth knowing before running anything against prod:
`maximum_bytes_billed = 100 GiB` per job in `profiles.yml`; physical storage
billing with 48h time travel on the analytics datasets; `profiles.yml` default
target is `dev` so a bare `dbt run` never touches prod.

## 6. Constraints a change must preserve

1. Do not add filesystem I/O outside `extraction/storage.py`, and do not
   construct a GCS client outside `cloud.py` / the CLI entrypoints.
2. Do not let `core` import `manifest` (bronze, upload) — runners are the only
   join point.
3. Do not put Dagster imports into `orchestration/convergence.py` or pass it
   live cloud clients; predicates stay pure.
4. Any local-data mutation from Dagster must happen inside
   `local_data_lock(..., EXCLUSIVE)`.
5. Bronze parses nothing nested and types no dates — that is staging's job.
   Staging classifies nothing — that is silver's job. Silver aggregates nothing.
6. Changing the bronze schema requires an explicit external-table recreation:
   `terraform apply -replace=google_bigquery_table.bronze_external` (the
   `ignore_changes = [schema]` lifecycle block means a schema edit produces
   **no** plan diff).
7. The GCS `upload/` manifest prefix must stay outside
   `bronze/publication_year=*/` or BigQuery will read it as a partition.
8. Preserve atomic-write discipline (tmp → fsync → rename) for every artifact a
   later stage treats as "exists ⇒ complete".
9. Extraction ordering on the fresh path must not be reordered (nothing on disk
   before a successful first fetch).

## 7. Uncertainty, inconsistency, known limitations

- **Comments and docstrings are self-contained by convention.** They state
  invariants and reasons; they do not cite documents. Two deliberate exceptions:
  code-to-code references, and cross-file contract mirrors (which name their
  counterparts on purpose). See `AGENTS.md` for the rule. Consequence for
  regeneration: the _why_ behind a constraint may live only in `DECISIONS.md`,
  not next to the code that enforces it.
- **No README.md yet** despite `pyproject.toml` declaring
  `readme = "README.md"`. Being written separately.
- **No CI configuration** in the repo; verification is local-only.
- **`docs/design-archive/` holds ten implemented and superseded design
  contracts.** They are archaeology, not current specification — several
  describe relations that no longer exist (`int_paper_half_life`,
  `gold_citation_half_life_by_subfield`) or bounds since advanced. Read them
  only when `DECISIONS.md` fails to explain something.
- **`extraction/runner.SELECT_COLUMNS` is an unguarded fourth copy of the bronze
  column list.** Changing it without changing `bronze/schema.py` breaks
  ingestion at read time rather than at edit time.
- **Q2 dev values do not preview prod.** `dbt_project.yml` states this
  explicitly: the dev 2012–2016 slice omits older cited works, so dev Q2 numbers
  are structurally valid but not representative. Q3 dev _is_ an exact
  overlapping-cohort preview.
- **Three independent year-bound var families** (`year_min/max`,
  `citation_age_year_min/max`, `gini_cohort_min`/`gini_citation_year_max`) that
  are advanced manually and only after a full-corpus refresh + prod
  reconciliation. Easy to desynchronize; check all three when changing bounds.
- **Known data caveats baked into staging**: works with NULL `is_retracted` are
  conservatively dropped by `= false`; at least one duplicate `id` exists and
  dedup is deferred from bronze to staging; `__unclassified__` in the Q3
  subfield model is a synthetic bucket, not a real subfield. Current counts and
  reconciliation baselines are in `FINDINGS.md` — do not restate them here,
  since this file is regenerated and would carry a stale copy.
- **Q2/Q3 quantiles are discrete integer years** — `counts_by_year` supports no
  within-year interpolation. Age 0 is diagnostic-only in Q3.
- **`scripts/` is largely superseded.** `openalex_downloader.py` and
  `bronze_ingest_spike.py` predate `src/openalex_pipeline/` and duplicate its
  concerns; `notebooks/` is exploratory. Do not treat either as current
  architecture.
- **Dagster instance state is disposable** (`.dagster/` is untracked); only
  `dagster.yaml` at the root is canonical.
- Importing `orchestration/definitions.py` runs `prepare_dbt_project` as a side
  effect — a dbt parse at module import. Any tooling that imports it needs a
  working dbt project and profile.
