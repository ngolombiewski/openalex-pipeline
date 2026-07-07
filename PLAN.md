# PLAN.md — Finishing the dbt project (STATE §Next, steps 4–8)

*Scope: take the warehouse foundation from "dbt parses clean, IAM applied" to a
full staging→silver→gold build answering Q1/Q2/Q3. Steps 4–8 of STATE.md.*

The plan is deliberately lopsided: **plumbing is spelled out to the command
level; modeling methodology is not.** Steps 4–6 (connectivity + staging) are
already specced in `docs/staging-design.md` and are mostly execution. Steps 7–8
(silver/gold) get their *infra scaffold* here, but the analytical methodology
(classification mechanics, half-life definition, Gini computation) is flagged
for a per-layer design doc — consistent with the project's
"design-doc-before-implementation" rule, and it is the careful part we want to
do slowly.

---

## Standing decisions (apply across all steps)

These are settled; they are not re-litigated per step.

- **`dbt_utils` is in.** Add to `dbt/packages.yml`, install with `dbt deps`.
  Gives `accepted_range`, `relationships`, `expression_is_true`,
  `unique_combination_of_columns` — reused heavily from staging onward.
- **All models materialize as `table`.** The corpus is static and fully
  rebuildable from the external table in one run. Incremental models are YAGNI
  here and add real complexity (unique keys, late-arriving logic) for no payoff
  on a ~14.7 M-row rebuild. Documented non-goal.
- **No new Terraform past this point.** The three datasets and the external
  table already exist and IAM is applied. Every silver/gold object is a dbt
  native table created *inside* `openalex_analytics` / `openalex_analytics_dev`,
  which `dbt-runner` already has `dataEditor` on. If a step turns out to need a
  new grant or dataset, that is a signal to stop and reconsider, not to quietly
  add it.
- **BigQuery partition + cluster on the big native tables.** `stg_works` and the
  silver works table get integer-range partitioning on `publication_year` and
  clustering on the subfield id (see step 5 for the exact config). Gold
  aggregates are tiny — no partitioning.
- **Dev = the 2012–2016 cohort slice, prod = full corpus**, via the existing
  `year_min`/`year_max` vars. Iterate on `--vars '{year_min: 2012, year_max:
  2016}'`; promote with `-t prod`. (Originally a 1991–2000 decade slice — steps
  4–6 ran on that — but retired: `counts_by_year` only covers 2012+, so a
  pre-2012 slice is useless for gold. The dev slice now equals the Q2/Q3
  analytical cohort, one canonical slice for all layers; 2.7 M rows, ~18% of
  corpus, ~8 GiB per staging rebuild.)

---

## Step 4 — Connectivity gate + smoke read

*Goal: prove the fragile path end-to-end (oauth → SA impersonation → external
read → bucket grant → write to dev → partition pruning) before writing any real
model.*

1. **Add `dbt_utils`.** Create `dbt/packages.yml`:
   ```yaml
   packages:
     - package: dbt-labs/dbt_utils
       version: [">=1.3.0", "<2.0.0"]
   ```
   Run `dbt deps`. (`dbt_packages/` is already gitignored.)
2. **`dbt debug`** from a direnv-active shell — confirms `profiles.yml`,
   impersonation, and the BigQuery connection resolve. Must be green.
3. **Run the smoke model against dev:**
   `dbt run --select _smoke` (target defaults to dev).
4. **Confirm partition pruning** in the BQ console / `bq` — bytes-billed for the
   1991–2000 slice should be a small fraction of the ~4.6 GB full scan, not the
   whole table. This is the real checkpoint (per staging-design §6); if pruning
   fails it is cheapest to catch here.
5. **Delete `dbt/models/staging/_smoke.sql`** and confirm a clean `dbt parse`.

**Done when:** `dbt debug` green, smoke build wrote one row to
`openalex_analytics_dev`, bytes-billed confirms pruning, `_smoke.sql` deleted.

---

## Step 5 — Staging model `stg_works`

*Fully specced in `docs/staging-design.md` §4–§5. This is execution. Below is
the build/test plumbing, not a re-derivation of the parse logic.*

1. **`models/staging/stg_works.sql`**, materialized `table`, with BigQuery
   partition + cluster config in the model header:
   ```sql
   {{ config(
       materialized='table',
       partition_by={'field': 'publication_year', 'data_type': 'int64',
                     'range': {'start': 1950, 'end': 2027, 'interval': 1}},
       cluster_by=['primary_topic_subfield_id']
   ) }}
   ```
   (Range end is exclusive; 77 partitions, far under BQ's 4000 limit.)
   Body does the four staging jobs and nothing else: parse the 8 JSON columns,
   type the two dates (`SAFE.PARSE_*`), filter (`is_retracted`/`is_paratext` +
   the corpus-bounds guard), dedup on `id` via `QUALIFY`. Per design §4a–§4f.
2. **`models/staging/_staging.yml`** — tests per design §5, now using
   `dbt_utils` where it helps:
   - `id`: `not_null`, `unique`.
   - `publication_year`: `not_null` + `dbt_utils.accepted_range` (1950–2026).
   - `primary_topic_subfield_id`: `not_null` at **`severity: warn`** first —
     observe the real null rate before hard-asserting (this feeds the silver
     denominator decision; see Open Decisions).
   - Date parse-failure singular tests (`tests/`): count non-NULL strings that
     `SAFE.PARSE_*` turned to NULL; expect ~0.
3. **Iterate on the dev decade slice:**
   `dbt build --select stg_works --vars '{year_min: 1991, year_max: 2000}'`
   (`build` = run + test in one shot). Loop until green.

**Done when:** `stg_works` builds and tests green on the dev slice;
`primary_topic_subfield_id` null rate observed and recorded (in STATE or the
silver design doc).

---

## Step 6 — Prod run + reconcile against the manifest

*Goal: the count gate. Staging over the full corpus must reconcile with the
bronze manifest, accounting for known drops.*

1. **`dbt build -t prod --select stg_works`** — full 1950–2026 corpus.
2. **Reconcile** `COUNT(*)` against `_MANIFEST.parquet` total (14,775,131).
   Expected delta = retracted + paratext filtered rows + the dedup drop (design
   §6 expects the dedup delta to be single-record-scale). Compute the breakdown
   so the number is *explained*, not just "close":
   - rows dropped by `is_retracted = TRUE`
   - rows dropped by `is_paratext = TRUE`
   - rows dropped by dedup
   - `manifest_total − (sum of drops) == stg_works row count` must hold exactly.
3. Record the reconciliation in STATE.

**Done when:** the identity above balances to the row and is written down.

---

## Step 7 — Silver: classification + flattening ✅ DONE (prod, pending review)

***Implemented per `docs/silver-design.md`.** `silver_works` built on prod:
14,723,333 rows (== staging), all tests green, `ai_strict` 27.49% / `ai_broad`
40.01% (on anchor), subset invariant holds in the data. The outline below is
what was built.*

### Scaffold (per `docs/silver-design.md`)

- **Layer config** in `dbt_project.yml`: a `silver:` block mirroring `staging:`
  (`+materialized: table`), plus the two pinned ablation vars `subfield_ai`
  (`…/1702`) / `subfield_cv_pr` (`…/1707`). Models live in `models/silver/`.
- **One model, `models/silver/silver_works.sql`** — one row per work,
  `ref('stg_works')` as the only input. Derives `is_ai_strict` / `is_ai_broad`
  (coalesced-boolean flags on the row, *not* an exploded variant table), and
  projects the staging columns down to the analytical set (§3 of the doc;
  `counts_by_year` carried nested). Same partition/cluster as staging.
- **`models/silver/_silver.yml`** + one singular test, reusing `dbt_utils`
  (`expression_is_true` for the `ai_strict ⊆ ai_broad` invariant and the two
  classification-correctness assertions; singular row-count test that silver ==
  staging — silver is a projection, never a filter).
- No new sources, no Terraform.

### Open decisions — now resolved in the design doc

1. **`ai_strict` / `ai_broad` mechanics** → match on subfield **id** (`1702`;
   `1702`+`1707`), pinned as `dbt_project.yml` vars. *Resolved.*
2. **primary_topic-less / NULL-subfield works** → moot in practice (0 nulls at
   full corpus, guaranteed by the `field.id:17` extraction filter); defensive
   default is non-AI + kept in the CS denominator. *Resolved.*
3. **Where `counts_by_year` is reshaped** → stays nested in silver; the long
   reshape + half-life methodology move to a **gold** intermediate (single
   consumer). *Resolved here, executed in step 8.*

**Done when:** `silver_works` builds + tests green on dev then prod; row count ==
`stg_works`; strict/broad shares land near the ≈27.5% / ≈40% anchor.

---

## Step 8 — Gold: analytical aggregates (Q1/Q2/Q3)

***Design doc written: `docs/gold-design.md` (pending review).** It specifies the
three computations and surfaces five flagged methodology decisions. The key
finding: `counts_by_year` is a fixed **2012–2026** window (verified), so Q2
half-life is cohort-restricted (post-2012); the age confound forces a cohort on
Q3 too. The outline below is superseded by the doc.*

### Scaffold (per `docs/gold-design.md`)

- **Layer config** in `dbt_project.yml`: `gold:` block, `+materialized: table`.
  Gold tables are tiny aggregates — no partitioning/clustering.
- **One model per question**, each grouped by the two ablation variants so the
  dashboard can toggle strict/broad:
  - `gold_ai_share_by_year` (Q1 — Takeover)
  - `gold_citation_half_life_by_subfield` (Q2 — Shelf Life)
  - `gold_citation_gini_by_subfield` (Q3 — Winner's Game)
- **`models/gold/_gold.yml`** tests with `dbt_utils.accepted_range`: shares in
  [0,1], Gini in [0,1], half-life positive. These bound-checks are the main
  guard against a silently-wrong aggregation.
- Inputs are `ref('silver_works')` (+ the citations fact for Q2). No new infra.

### Open decisions — now in the design doc (§6), to settle at review

1. **Q1 denominator** → resolved in silver: all `silver_works` are CS, 0 null
   subfields. Denominator = all works in the year. *Resolved.*
2. **Q2 half-life** → defined (cumulative-to-50% citation age) + cohort-restricted
   to 2012–2016 (forced by the `counts_by_year` window). Open: exact cohort
   bounds, interpolation. *Flagged in doc §6.*
3. **Q3 Gini** → SQL formula pinned; cohort-controlled; zeros included. Open:
   cohort choice, optional cited-only secondary. *Flagged in doc §6.*

**Done when:** the doc's flagged decisions are settled; all three gold tables
build + test green on dev (the canonical 2012–2016 slice)
then prod; headline AI-vs-rest comparisons sanity-checked before the dashboard.

---

## Sequencing note

4 → 5 → 6 are a straight execution run and can be done in one sitting; the only
gate is the step-4 pruning check and the step-6 reconciliation. **7 and 8 each
pause for a design doc** — that is the intended speed change: fast through the
plumbing, deliberate at the modeling. Dagster orchestration (STATE step 9) wraps
all of this afterward and is out of scope here.
