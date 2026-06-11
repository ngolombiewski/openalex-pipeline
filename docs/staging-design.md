# Design: Warehouse Foundation (Terraform → external table → dbt init → staging)

*Scope: the seam between the Python pipeline and the warehouse. Stands up the
BigQuery datasets, the bronze external table over GCS, the dbt project, and the
staging layer. Stops before AI classification (silver) and aggregates (gold).*

*Status: design — to hand to an implementing agent.*

---

## 0. What this layer is

Bronze Parquet already lives in GCS at
`gs://openalex-pipeline-bronze/bronze/publication_year=YYYY/YYYY.parquet`
(77 years, ~4.6 GB, Hive-partitioned path). This layer makes that data
queryable in BigQuery and produces the first native table.

The architecture from `ARCHITECTURE.md` holds: **Terraform owns infrastructure
up to and including the external table; dbt owns everything native downstream.**
The external table is a pointer-to-GCS with a schema declaration — pure infra,
no SQL logic — so it belongs to Terraform, not to dbt. We deliberately do *not*
pull in the `dbt-external-tables` package; for a single source it is overkill.

```
Terraform                              dbt
  dataset openalex_raw                   staging.stg_works  (native table)
  dataset openalex_analytics
  dataset openalex_analytics_dev
  external table:
    openalex_raw.bronze_external
    → gs://.../bronze/  (Hive-partitioned)
         │                                     │
         └──────────── dbt source ─────────────┘
```

dbt declares `bronze_external` as a **source** (a table it did not build) and
materializes `stg_works` as a **native table** — the first layer where real
work (JSON parsing) is paid for, and paid for once.

---

## 1. Terraform: datasets

Add to the existing `terraform/` project (which already provisions the GCS
bucket, state backend, SA impersonation). Reuse the existing provider, project,
and region (`EU` / `europe-west*` — match the bucket's `EU` location; BigQuery
dataset location **must** match the GCS bucket location or external queries
fail).

Three datasets:

| Dataset | Purpose |
|---|---|
| `openalex_raw` | Holds the external table (and only that). The GCS-handoff namespace. |
| `openalex_analytics` | dbt prod target — staging/silver/gold native tables. |
| `openalex_analytics_dev` | dbt dev target — same models, built over a year *slice* (see §3b). |

`google_bigquery_dataset` resources. Set `location` to match the bucket.

`delete_contents_on_destroy`:
- `true` on the two analytics datasets. Their contents are dbt-built native
  tables, rebuildable from the external table with one `dbt run` — so
  `terraform destroy` may delete them without ceremony.
- `false` (the default) on `openalex_raw`. Not because anything irreplaceable
  lives there — the dataset holds only the external table *definition*, a
  pointer; the data itself is Parquet in GCS, and the parsed/typed results
  live in the analytics datasets. The reason is that `false` makes destroy a
  loud guard: Terraform deletes the external table it manages, and if the
  dataset is then empty, destroy succeeds. If anything *else* has landed in
  `openalex_raw` (something Terraform doesn't know about), destroy fails
  instead of silently deleting it. Corruption-is-loud, applied to infra.

---

## 2. Terraform: the bronze external table

This is the highest-risk resource in the whole layer. Three things must be
right or it silently misbehaves.

Resource: `google_bigquery_table` with an `external_data_configuration` block.

### 2a. Source URI + format
- `source_format = "PARQUET"`
- `source_uris = ["gs://openalex-pipeline-bronze/bronze/*"]`
  (the wildcard spans all `publication_year=YYYY/` prefixes)

### 2b. Hive partitioning — **do not omit**
The GCS path scheme exists *solely* for partition pruning (`ARCHITECTURE.md`,
"Path conventions across the boundary"). Without this block, every query scans
all 77 years.

```hcl
hive_partitioning_options {
  mode                     = "CUSTOM"
  source_uri_prefix        = "gs://openalex-pipeline-bronze/bronze/{publication_year:INTEGER}"
  require_partition_filter = false
}
```

- `CUSTOM` mode (not `AUTO`) lets us pin the key name and type explicitly
  rather than letting BQ guess from the path.
- `require_partition_filter = false`: the analytical questions are
  time-series across *all* years (Q1 is literally "share over time"), so we
  must allow unfiltered scans. Do not set this `true`.

### 2c. The `publication_year` collision — **verify explicitly**
`publication_year` exists **both** inside the Parquet (as `int`, per
`DATA_MODEL.md`) **and** as the Hive partition key derived from the path. These
must resolve to a single `INT64` column, not a duplicate or a type clash.

Implementer action: after `terraform apply`, run
`SELECT publication_year, COUNT(*) FROM openalex_raw.bronze_external GROUP BY 1
ORDER BY 1` and confirm:
- exactly one `publication_year` column,
- typed `INT64`,
- 77 distinct values 1950–2026,
- counts that match `_MANIFEST.parquet` per-year rows.

If BQ rejects the table for a column/partition-key name collision, the fix is
to declare an explicit `schema` in the external config that **omits**
`publication_year` from the file columns and lets the partition key supply it.
Try the implicit path first; fall back to explicit schema only if it collides.

*Outcome (implemented): the collision is real — BigQuery rejects creation when
a field appears in both the schema and the partition key — so
`terraform/bigquery.tf` declares the explicit schema without
`publication_year`, plus `ignore_changes = [schema]` to suppress the
partition column the API appends on read-back.*

### 2d. Schema: explicit, not autodetect
Declare the full column schema in the external config rather than relying on
`autodetect`. The column list is pinned in `DATA_MODEL.md` ("Included
columns"). The eight nested fields are **`STRING`** (they are raw JSON strings
in bronze — autodetect would also call them `STRING`, but we declare it so the
contract is visible and version-controlled). Scalars per the `DATA_MODEL.md`
type column. `publication_date` and `updated_date` are `STRING` here — date
typing is deferred to staging by design.

---

## 3. dbt: project init

Self-contained dbt project at `/dbt/` (already in the repo layout in
`ARCHITECTURE.md`). `dbt-bigquery` adapter.

### 3a. profiles.yml — two targets
```yaml
openalex:
  target: dev          # safe default: never nuke prod by forgetting a flag
  outputs:
    dev:
      type: bigquery
      method: oauth                    # or SA impersonation — match the
                                       # mechanism Terraform already uses
      project: "{{ env_var('OPENALEX_GCP_PROJECT') }}"
      dataset: openalex_analytics_dev
      location: EU                     # must match bucket + datasets
      threads: 4
    prod:
      type: bigquery
      method: oauth
      project: "{{ env_var('OPENALEX_GCP_PROJECT') }}"
      dataset: openalex_analytics
      location: EU
      threads: 8
```
`target: dev` as the default is deliberate — running `dbt run` with no `-t`
flag should hit dev, never prod. Prod is opt-in (`dbt run -t prod`).

Note: `env_var()` without a default fails at parse time when the variable is
unset, and dbt does not read `.env` itself. `OPENALEX_GCP_PROJECT` reaches dbt
via direnv (`.envrc` → `dotenv` → `.env`); run dbt from a direnv-active shell
or export the variable first.

### 3b. dbt_project.yml — materializations + corpus bounds
```yaml
models:
  openalex:
    staging:
      +materialized: table     # parse-once; never a view over the external table

vars:
  year_min: 1950               # corpus bounds — honest prod defaults
  year_max: 2026
```

**On the var semantics (this is the important bit).** `year_min`/`year_max`
are the *corpus bounds*, not a "dev sample" knob. Prod genuinely wants
1950–2026 — that is the real corpus, and the defaults say so. Dev narrows the
bounds to a **slice** to iterate cheaply. Same mechanism, honest meaning:

- Prod: `dbt run -t prod` → defaults → full corpus.
- Dev:  `dbt run` (defaults to dev target)
  `--vars '{year_min: 1991, year_max: 2000}'` → one decade, fast iteration.

The dev slice is a mid-corpus **range**, not a raised floor. Recent partitions
are much larger (the corpus grows steeply), so "last 2 years" is both
expensive and temporally degenerate. A decade like 1991–2000 is a small
fraction of the bytes yet rich enough to exercise the temporal models
(year-over-year share, citation aging) — the models that matter must see a
multi-year window. Both bounds must therefore be real, first-class vars; a
floor alone cannot express this.

Do **not** invent a separate `is_dev` boolean or a row `LIMIT` — those decouple
the sample from the partition key and defeat pruning. The whole point is that
narrowing the bounds prunes Parquet partitions at the external-table read.

### 3c. sources.yml — declare the external table
```yaml
sources:
  - name: bronze
    database: "{{ env_var('OPENALEX_GCP_PROJECT') }}"
    schema: openalex_raw
    tables:
      - name: bronze_external
```
Referenced in staging as `{{ source('bronze', 'bronze_external') }}`.

---

## 4. dbt: the staging model

`models/staging/stg_works.sql`, materialized `table`.

Staging does exactly four things — **parse, type, filter, deduplicate** — and
nothing else. No classification (that is silver). No aggregation (that is
gold).

### 4a. Parse all eight JSON-string columns
Parse every nested field now, not lazily. Rationale: staging materializes once;
re-parsing later forces a re-read of the external table. Parse-everything-once
is cheaper over the project's life even for low-signal fields (`keywords`,
`cited_by_percentile_year`).

Use BigQuery `JSON_*` functions / `PARSE_JSON` + `JSON_VALUE` /
`JSON_QUERY_ARRAY` as appropriate per field shape:

| Bronze field (JSON string) | Staging output |
|---|---|
| `primary_topic` | Extract `id`, `display_name`, `subfield.id`, `subfield.display_name`, `field.id`, `field.display_name` into flat columns. **Critical for classification downstream.** |
| `counts_by_year` | Parse to an `ARRAY<STRUCT<year INT64, cited_by_count INT64>>`. **Critical for half-life (Q2).** Keep as a typed nested column; do not pre-aggregate. |
| `topics` | Parse to typed array; retained, not used for classification (`DATA_MODEL.md`). |
| `open_access` | Flatten `is_oa`, `oa_status`. |
| `ids` | Flatten the crosswalk keys present. |
| `cited_by_percentile_year` | Flatten min/max fields. Low signal — light parse. |
| `citation_normalized_percentile` | Flatten value + is_in_top fields. |
| `keywords` | Typed array. Low signal — light parse. |

Implementer note: OpenAlex records have heterogeneous presence of keys
(`DATA_MODEL.md` notes the forced-String choice in bronze was *specifically* to
avoid fabricating nulls for absent keys). So extraction must tolerate missing
keys — `JSON_VALUE` returns NULL for an absent path, which is correct and
intended. Do not "repair" these nulls.

### 4b. Type the deferred date columns
`publication_date` (string → `DATE`) and `updated_date` (string →
`TIMESTAMP`). Both are deferred from bronze by design (`DATA_MODEL.md`). Use
`SAFE.PARSE_DATE` / `SAFE.PARSE_TIMESTAMP` so a malformed value yields NULL
rather than failing the whole model; add a dbt test to count NULLs and confirm
the rate is ~0.

### 4c. Apply data-quality filters
`WHERE is_retracted = FALSE AND is_paratext = FALSE` — the two filters flagged
as "Data quality filter" in `DATA_MODEL.md`. These belong in staging (they are
corpus hygiene, not analysis).

### 4d. The corpus-bounds guard
```sql
where publication_year between {{ var('year_min') }} and {{ var('year_max') }}
```
Combined with 4c into one `WHERE`. This is the line that makes dev cheap and
prunes partitions at the external read. Both bounds always render — the prod
defaults are the true corpus bounds (§3b), so there is no "unbounded" branch
to special-case.

### 4e. Deduplicate on `id`
Deduplication was deliberately deferred from bronze to staging, and it is not
hypothetical: the real data contains at least one duplicate `id`, detected at
bronze ingestion (most likely a stale extraction cursor re-emitting a page).
The `unique` test in §5 is only honest if staging dedups first.

```sql
qualify row_number() over (
  partition by id
  order by updated_date desc
) = 1
```

Keep the copy with the latest `updated_date` (the fresher OpenAlex snapshot).
On an exact tie the pick is arbitrary, which is acceptable: tied duplicates
from a re-emitted page are byte-identical records. Note `updated_date` is
still a `STRING` at this point, but OpenAlex emits ISO-8601, which orders
correctly lexicographically — dedup does not depend on §4b's parsing.

Order of operations: the `WHERE` filters (4c/4d) apply first, then `QUALIFY`
dedups the survivors. A duplicate pair could in principle straddle the dev
slice boundary (copies sharded under different `publication_year`s); then only
one copy is in scope and there is nothing to dedup — correct, not a bug.

### 4f. Keep `id` as primary key, asserted
`id` is the non-null primary key (`DATA_MODEL.md`). Carry it through verbatim;
unique after 4e, by construction.

---

## 5. Tests (`models/staging/_staging.yml`)

Minimum dbt tests on `stg_works`:
- `id`: `not_null`, `unique` (valid only because §4e dedups first — the raw
  data is known to contain at least one duplicate).
- `publication_year`: `not_null`; accepted range 1950–2026 (a dbt
  `accepted_range` via `dbt_utils`, or a singular test).
- `primary_topic_subfield_id`: `not_null` for the vast majority — but **do not
  hard-assert non-null** until you have checked the real null rate; OpenAlex
  has works without a fully populated primary_topic. Spec: add the test as
  `warn` severity first, observe, then decide. (Classification in silver will
  have to handle primary_topic-less works regardless — flag this for the silver
  design.)
- `publication_date` / `updated_date`: a singular test counting non-NULL parse
  failures, expected ~0.

Run `dbt test -t dev` against the dev decade slice first.

---

## 6. Implementation order (for the agent)

1. **Terraform datasets** (§1) → `apply`. Cheap, reversible.
2. **Terraform external table** (§2) → `apply`. Then run the §2c verification
   query. **Do not proceed until the `publication_year` column is confirmed
   single + `INT64` + 77 years.** This is the gate.
3. **dbt init** (§3): project skeleton, `profiles.yml`, `sources.yml`,
   `dbt_project.yml`. Verify connectivity: `dbt debug`, then
   `dbt run-operation` or a trivial `SELECT 1` model against dev.
4. **Sanity-query the source through dbt** before writing staging: a throwaway
   model `SELECT COUNT(*) FROM {{ source('bronze','bronze_external') }} WHERE
   publication_year BETWEEN 1991 AND 2000` — confirms the source resolves
   *and* that the partition filter prunes (check bytes-billed in the BQ
   console; it should be the decade's worth, not 4.6 GB).
5. **staging model** (§4) + tests (§5), iterate on dev
   (`--vars '{year_min: 1991, year_max: 2000}'`).
6. **Prod run**: `dbt run -t prod` once staging is stable on dev. Confirm row
   count against `_MANIFEST.parquet` totals (minus the retracted/paratext
   filter drop and the §4e duplicate drop — expect the dedup delta to be tiny,
   on the order of single records).

Step 4 is the one most likely to reveal a problem (partition pruning not
working, schema mismatch) while it is still cheap to fix — treat it as the real
checkpoint, not step 6.

---

## 7. Open questions deferred to silver (flag, don't solve here)

- **primary_topic-less works**: how does classification treat works with a NULL
  `primary_topic.subfield.id`? They cannot be `ai_strict`/`ai_broad` either
  way, but should they be in the CS denominator at all? (Bronze is already
  filtered to `field.id:17`, so a work is CS by primary_topic.field — but a
  NULL subfield is possible.) Resolve in silver design.
- **`ai_strict` vs `ai_broad`** mechanics (the CV/PR ablation) — silver.
- Whether `counts_by_year` needs reshaping (kept nested in staging) into a long
  table for the half-life computation — likely a gold concern.

---

## 8. What "done" looks like

- `terraform apply` provisions three datasets + one external table; the
  verification query passes.
- `dbt debug` green; `dbt run` (dev) builds `stg_works` over the dev decade
  slice in seconds; `dbt run -t prod` builds it over the full corpus.
- `dbt test` green (or `warn`-only on the deliberately-soft primary_topic test).
- A reviewer can read this doc + the repo and see that external-vs-native was
  *exercised* (bronze external, staging native), not merely asserted.
