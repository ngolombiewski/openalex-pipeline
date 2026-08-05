# OVERVIEW.md

Architecture, data flow, boundaries, and contracts. Derived from source; read
this first in any session.

**Ref:** `bcf48d1` — regenerate when the source it describes moves.

For *why* a design is the way it is, see `DECISIONS.md`. For *what the numbers
are*, see `FINDINGS.md`.

---

## 1. What this is

An end-to-end pipeline over the OpenAlex computer-science corpus (publication
years 1950–2026), answering three questions:

<!-- prettier-ignore -->
| | Question | Gold model |
|---|---|---|
| Q1 | AI's share of CS works per publication year | `gold_ai_share_by_year` |
| Q2 | Citation-weighted age of cited works | `gold_citation_age_by_year` |
| Q3 | Citation concentration (Gini/top-k) | `gold_citation_gini_by_subfield`, `gold_citation_gini_by_group` |

Python does extraction and local landing; BigQuery + dbt do the warehouse;
Dagster orchestrates; Terraform owns the infrastructure.

---

## 2. Data flow

```
OpenAlex API                     (filter: OPENALEX_FILTER, one query per year)
  → extraction/   data/extract/{year}/page-NNNN.jsonl  + _META/_CURSOR/_YEAR_REPORT
  → bronze/       data/bronze/{year}.parquet           + _MANIFEST.parquet
  → upload/       gs://…/bronze/publication_year={year}/{year}.parquet
                                                        + upload/_MANIFEST.parquet
  → BigQuery external table  openalex_raw.bronze_external   (Terraform-owned)
  → dbt staging   stg_works        parse / type / filter / dedup
  → dbt silver    silver_works     AI classification + projection
  → dbt gold      gold_*           question-shaped aggregates
```

Every stage is both a standalone CLI (`python -m openalex_pipeline.<stage>`) and
a Dagster asset. Any layer can be run and debugged alone.

**Filesystem as source of truth.** No stage keeps state anywhere but on disk (or
in GCS blob metadata). File presence and atomic rename are the completion
signals; both manifests are *derived* artifacts, rebuilt wholesale each run and
never read back as authority.

---

## 3. Python packages (`src/openalex_pipeline/`)

### 3.1 `extraction/`

Paginates the OpenAlex API into JSONL, resumably.

- **`settings.py`** — the only runtime-configuration module. Reads
  `OPENALEX_API_KEY`, `OPENALEX_FILTER`, `OPENALEX_START_YEAR`,
  `OPENALEX_END_YEAR`, `OPENALEX_DATA_ROOT` (landing zone is
  `{data_root}/extract`). Everything else is a pinned constant.
- **`runner.py`** — pure orchestration, no I/O. Owns the canonical query:

  ```
  works?filter={filter},publication_year:{year}&select={SELECT_COLUMNS}&per_page=200
  ```

  Parameter and filter order are owned here; the connector may append `cursor`
  and the API key in any order without changing query identity.
- **`connector.py`** — the single HTTP call plus retry/backoff (5 attempts,
  exponential from 1.0s, factor 2). The primary test seam: `fetch_page` is
  injected into the worker, so the suite needs no network.
- **`worker.py`** — a pure state machine over one year directory. The pinned
  loop is written out in its module docstring; the fresh-path order
  `fetch_page → initialize_year → write_page` guarantees a first-fetch failure
  leaves nothing on disk.
- **`storage.py`** — all filesystem I/O, five public functions
  (`classify_year`, `initialize_year`, `write_page`, `finalize_year`,
  `read_year_report`), all taking `(root, year)` first. Atomic durable writes
  (tmp + flush + fsync + rename); `_META.json` and `_YEAR_REPORT.json` are
  immutable once written.
- **`exceptions.py`** — two base classes by origin: `ConnectorError`,
  `StorageError`. `DailyLimitReached` is a clean expected stop, not a failure;
  the runner catches it and returns a partial report
  (`status="stopped_daily_limit"`). Everything else propagates.

**Year-shard states:** `FRESH → IN_PROGRESS → COMPLETE`. `COMPLETE` is the
presence of `_YEAR_REPORT.json`. The finalize-pending sub-state (all pages
written, report owed) is deliberately *not* a fourth enum value — it is
`IN_PROGRESS` with `cursor is None`. Any file combination outside the three
legal states raises `CorruptedState`; there is no recovery path.

### 3.2 `bronze/`

JSONL → one Parquet per year.

- **`schema.py`** (leaf) — `BRONZE_SCHEMA`: **21 columns**, imposed on read, no
  inference. Eight nested columns (`primary_topic`, `topics`, `counts_by_year`,
  `cited_by_percentile_year`, `citation_normalized_percentile`, `open_access`,
  `ids`, `keywords`) land as `pl.String` holding verbatim OpenAlex JSON.
  `publication_date` and `updated_date` are `pl.String` — date typing is
  deferred to dbt staging. Scalar dtypes are load-bearing: a non-conforming
  value raises a Polars `ComputeError` at read.
- **`core.py`** — year classification (`INGESTED` / `READY` / `PENDING`), the
  corpus-level query-homogeneity assertion (one landing zone holds exactly one
  filter/select across all shards), and single-year ingest.
- **`manifest.py`** — `_MANIFEST.parquet`, re-derived from the filesystem every
  run. Does *not* import `core`; it re-derives status independently, with the
  status strings matching `core.YearState` by contract.
- **`runner.py`** — the only module touching both `core` and `manifest`.

### 3.3 `upload/`

Bronze Parquet → GCS, skip-aware.

- Object layout: `bronze/publication_year={year}/{year}.parquet`. The Hive
  prefix exists solely for BigQuery partition pruning.
- Skip decision is local mtime vs. blob metadata.
- The GCS bucket is **injected**, never constructed in `core` — one mockable
  cloud seam.
- `upload/_MANIFEST.parquet` sits deliberately *outside* the `bronze/` tree
  BigQuery globs, so it can never be mistaken for a partition. Uploaded last,
  so its presence signals a complete run.
- Same sibling split as bronze: `core` and `manifest` are independent; only
  `runner` touches both.

### 3.4 `orchestration/`

Dagster. See §6.

---

## 4. Warehouse (`dbt/`)

Profile `openalex` lives in-repo at `dbt/profiles.yml` (found via
`DBT_PROFILES_DIR=dbt`). Auth mirrors Terraform: OAuth ADC impersonating
`dbt-runner@…`, no key file. **Target defaults to `dev`** — a bare `dbt build`
can never touch prod. `maximum_bytes_billed` is 100 GiB per job on both targets.

<!-- prettier-ignore -->
| Target | Dataset |
|---|---|
| `dev` | `openalex_analytics_dev` |
| `prod` | `openalex_analytics` |

### 4.1 Layer boundaries

Each layer does exactly one job, and the boundaries are stated in the model
headers:

- **`stg_works`** (table, partitioned on `publication_year`, clustered on
  `primary_topic_subfield_id`) — does four things and nothing else: parse the
  eight JSON-string columns, type the two date columns, apply the corpus-hygiene
  filters, deduplicate on `id`. No classification, no aggregation.
  - Filters: `is_retracted = false and is_paratext = false` (the `= false` form
    also drops NULL-status rows, deliberately) and the `year_min`/`year_max`
    bounds guard, which is also what prunes external-read partitions.
  - Dates use `safe.parse_*` so a malformed value yields NULL rather than
    failing the model; singular tests assert the parse-failure count is ~0.
  - Dedup: `qualify row_number() over (partition by id order by updated_date
    desc nulls last) = 1`. Deferred from bronze because it needs the parsed
    `updated_date`.
  - `counts_by_year` is kept **nested and typed**, never pre-aggregated — Q2 and
    Q3 both consume it.
- **`silver_works`** (same grain, same partition/cluster) — AI classification
  plus projection. No filter, no aggregation: trust the layer below. Adds
  `is_ai_strict` / `is_ai_broad`, kept strictly boolean via `coalesce(…, false)`
  so a NULL subfield is non-AI and stays in the CS denominator.
- **`gold_*`** (tables, tiny, unpartitioned) — one model per question shape.

### 4.2 Vars (the pinned contract)

<!-- prettier-ignore -->
| Var | Prod value | Meaning |
|---|---|---|
| `year_min` / `year_max` | 1950 / 2026 | corpus publication bounds |
| `subfield_ai` | subfield `1702` | Artificial Intelligence |
| `subfield_cv_pr` | subfield `1707` | Computer Vision and Pattern Recognition |
| `citation_age_year_min` / `_max` | 2012 / 2025 | Q2 citation-year window |
| `gini_cohort_min` | 2012 | Q3 earliest cohort |
| `gini_citation_year_max` | 2025 | Q3 window ceiling |
| `partial_year` | 2026 | year Q1 flags as in-flight |

**AI is pinned by stable subfield id, never display name.** The id is the stable
upstream key; the name is a presentation string. Both variants are carried
through every downstream model, so each result has a built-in sensitivity check.

**The three year-bound families are independent and advance independently.**
Corpus bounds, Q2 citation bounds, and Q3 window bounds are separate vars on
purpose: citation histories live on cited works across every publication shard,
so current-year-only automation cannot extend Q2 or Q3. Q3's latest usable
cohort is *derived* as `gini_citation_year_max - 1`, not configured. Q3's 2012
floor is forced by the rolling `counts_by_year` window — earlier cohorts would
fabricate zero-citation papers.

Dev slice: `dbt run --vars '{year_min: 2012, year_max: 2016}'` — an exact
overlapping-cohort preview for Q3, a cheap structural target for Q2 (dev Q2
values do **not** preview prod, since the slice omits older cited works).

### 4.3 Gold grains

- **`gold_ai_share_by_year`** — `publication_year × variant` (`strict`/`broad`),
  long so a dashboard toggle is a filter, not a pivot. Six enforced columns:
  `publication_year, variant, cs_works, ai_works, share, is_partial_year`. No
  cohort restriction — a within-year ratio is immune to the citation-window
  confound.
- **`gold_citation_age_by_year`** — `citation_year × cited_group`, where
  `cited_group ∈ {ai, cv_pr, rest_cs}` is mutually exclusive and classifies the
  **cited** work, not the unknown citing work. Ages are discrete integer years
  (the source is annual), so quantiles are the smallest age whose cumulative
  event weight reaches q — no within-year interpolation is supported.
- **`gold_citation_gini_by_subfield`** — `subfield_id × publication_year ×
  citation_age` (primary Q3 relation). `citation_age` is the *cumulative* window
  of complete calendar years 1..n after publication; every paper stays in every
  observable window, uncited papers included. `__unclassified__` is a synthetic
  bucket preserving the silver denominator, not a real subfield. Age 0 is
  excluded from the measures and exposed via `age0_citation_share` and
  `zero_share_including_age0`.
- **`gold_citation_gini_by_group`** — `cited_group × publication_year ×
  citation_age`, the *secondary pooled* comparison. `rest_cs` pools many
  subfields, so it is **not** a like-for-like substitute for the subfield
  relation: the two are two relations at different grains, not one filterable
  table. Consumers must respect that.

Both Q3 models share `macros/q3_paper_windows.sql`. Gini uses exact integer
value frequencies; top-k shares take `ceil(k * n_papers)` from the full cohort
and allocate tied boundary frequencies so the result is independent of paper
ordering.

### 4.4 Tests

116 dbt data tests (schema-level: uniqueness, not-null, accepted values,
accepted ranges, expression checks) plus 25 singular tests in `dbt/tests/` —
cross-grain reconciliation, cohort floors, quantile/share ordering, triangle
completeness, identity constraints, and date-parse assertions. One
(`warn_citation_age_negative_entries`) is an expected warning, not a failure.

---

## 5. Infrastructure (`terraform/`)

- **Bucket** `openalex-pipeline-bronze`, location `EU`.
- **Datasets** (all `EU`, which must match the bucket):
  - `openalex_raw` — GCS-handoff namespace, holds only the external table.
    `delete_contents_on_destroy = false` as a loud guard.
  - `openalex_analytics`, `openalex_analytics_dev` — dbt targets;
    rebuildable, so `delete_contents_on_destroy = true`. Both use
    `PHYSICAL` storage billing with `max_time_travel_hours = 48`.
- **`bronze_external`** — external table over the Hive-partitioned Parquet.
  Schema is **pinned, not autodetected**, and mirrors `bronze.schema.BRONZE_SCHEMA`.
  `publication_year` comes from the partition key and must not appear in the
  declared schema. A `lifecycle { ignore_changes }` block suppresses the
  permanent API-side diff — with the consequence that a deliberate schema change
  produces **no plan diff** and requires
  `terraform apply -replace=google_bigquery_table.bronze_external`.
- **IAM** — no credentials on disk. ADC impersonates the `dbt-runner` service
  account; the caller's ADC must hold `tokenCreator` on it.

### The three-place schema contract

The bronze schema is declared in three places and pinned in all three:

1. `src/openalex_pipeline/bronze/schema.py` (Polars)
2. `terraform/bigquery.tf` (external-table schema)
3. `dbt/models/staging/stg_works.sql` (the parse)

`tests/bronze/test_schema_mirror.py` parses the Terraform file and asserts it
agrees with the Python schema on names, order, types, and nullability — those
two can drift silently. The dbt leg fails loudly on its own.

---

## 6. Orchestration (`src/openalex_pipeline/orchestration/`)

**Convergence-based, not schedule-based.** Importing `definitions.py` is a
startup action: it prepares a current prod-target dbt manifest (serialized on
`dbt/.prepare.lock`, always re-parsed) before Dagster reads the asset graph.

**Assets:** `extracted_jsonl → bronze_parquet → bronze_gcs → openalex_dbt_assets`.
The dbt `bronze` source is remapped by `OpenAlexDbtTranslator` onto the
`bronze_gcs` asset key, so the graph is continuous across the Python/dbt seam.

**Jobs, schedules, sensors** — all default to `RUNNING`:

<!-- prettier-ignore -->
| Trigger | Cadence | Effect |
|---|---|---|
| `local_sweep_schedule` | `0 4 * * *` Europe/Berlin | extraction → bronze → upload |
| `invalidate_refresh_year_schedule` | `0 3 1 * *` Europe/Berlin | request invalidation of the current year |
| `warehouse_staleness_sensor` | every 4h | request one prod `dbt build`, max 3 retries |

**Locking.** `data/.orchestration.lock`: writers take `LOCK_EX` and block;
the sensor takes `LOCK_SH | LOCK_NB` and skips immediately if a writer holds it.

**The sensor's predicate chain** (any failure is a `SkipReason`, not an error):

1. no `warehouse_build` already in flight;
2. lock acquired shared;
3. `is_converged(...)` — no pending invalidation tombstone, and every expected
   year has COMPLETE extraction, local bronze Parquet, and matching GCS state;
4. `warehouse_is_stale(...)` — every expected dbt relation exists, and
   `max(uploaded_at) > min(modified)` over expected **tables** only (view
   timestamps do not participate in freshness).

Run key is the latest upload timestamp, so one converged state produces one build.

**Invalidation** is a durable request/executor protocol: the monthly job writes
an `_INVALIDATING_{year}` tombstone (non-destructive), and the next extraction
run executes it under the exclusive lock before extracting. Malformed or
out-of-bounds tombstones raise `TombstoneCorruption`.

**Typed failures:** `TombstoneCorruption`, `UploadManifestInvalid`,
`UnsupportedDbtMaterialization` (only `table`/`view` are supported),
`WarehouseMetadataInvalid`.

⚠️ `dagster dev` is not a harmless graph viewer — it starts the production
automation, since all three triggers default to `RUNNING`.

---

## 7. Verification

- **255 pytest tests**, no network and no cloud calls (the HTTP connector and
  the GCS bucket are injected seams). `tests/` mirrors the package structure.
- **116 dbt data tests + 25 singular tests** (see §4.4).
- Clean under `ruff check`, `ruff format --check`, and `pyright`.
- **CI** (`.github/workflows/ci.yml`, on push to `main` and every PR): ruff
  lint, ruff format, pyright, pytest, `dbt deps`, `dbt parse`, and
  `dagster definitions validate` — no GCP credentials required
  (`OPENALEX_GCP_PROJECT` is a placeholder; nothing authenticates or queries).

---

## 8. Configuration surface

All env vars are in `.env.example`; `.envrc` (direnv) exports them and sets up
`DAGSTER_HOME`.

<!-- prettier-ignore -->
| Var | Consumer |
|---|---|
| `OPENALEX_API_KEY` | extraction connector — credential; never logged, written, or part of query identity |
| `OPENALEX_FILTER` | extraction runner — filter expression *without* `publication_year` and *without* `filter=` |
| `OPENALEX_START_YEAR` / `_END_YEAR` | extraction bounds, and the year set orchestration expects |
| `OPENALEX_DATA_ROOT` | all local layers (`{root}/extract`, `{root}/bronze`) |
| `OPENALEX_GCS_BUCKET` | upload, orchestration |
| `OPENALEX_GCP_PROJECT` | dbt `profiles.yml` and `_sources.yml` |
| `DBT_PROFILES_DIR` | `dbt` (in-repo, non-default profile location) |
| `DBT_LOG_PATH` | `dbt/logs` — otherwise dbt drops `logs/` at the repo root |

---

## 9. Repository map

<!-- prettier-ignore -->
| Path | Contents |
|---|---|
| `src/openalex_pipeline/` | `extraction/`, `bronze/`, `upload/`, `orchestration/` |
| `dbt/` | staging, silver, gold models; `macros/`; `tests/` (singular); in-repo `profiles.yml` |
| `terraform/` | bucket, three datasets, external table, IAM |
| `tests/` | pytest suite, mirroring the package structure |
| `scripts/`, `notebooks/` | exploration and diagnostics; not part of the pipeline |
| `tools/` | `render_q1_chart.py`, `context_size.py` |
| `assets/` | committed Q1 gold extract and the rendered charts |
| `docs/dashboard-spec.md` | the remaining layer (Streamlit over gold), spec only |
| `docs/design-archive/`, `docs/openalex/` | archaeology; vendored upstream docs |

---

## 10. Current state and known gaps

- The pipeline is complete through gold and reconciled at full corpus. The
  **Streamlit dashboard is the one unbuilt layer** (`docs/dashboard-spec.md`).
- **Automation refreshes the current publication year only.** It does not
  extend Q2 citation windows or Q3 cohorts, and does not re-run classification.
  Advancing those bounds is a deliberate manual operation, done only after a
  full reconciliation.
- **Year rollover is manual**, requiring coordinated changes to the extraction
  bounds and the dbt year vars.
- **Q3's earliest cohorts may become unrebuildable**: OpenAlex's per-year
  citation counts are a rolling window, so a future re-extraction may drop the
  earliest citation years. No mitigation is in place.
- The most recent cohort carries a settling caveat a single snapshot cannot
  fully resolve; see `FINDINGS.md`.
