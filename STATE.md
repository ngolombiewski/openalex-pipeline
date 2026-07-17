# STATE.md

*Last updated: 2026-07-17*

Edit at the **end** of every session whose work changes the state. If this
file falls more than a session or two behind, throw it out and rewrite —
stale state is worse than no state.

## Complete

- **Extraction module** — fully implemented, tested, and deployed locally.
  Daily pulls have completed all years from 1950 through 2025 against the
  OpenAlex free tier. 2026 is partial (in-flight; expected and normal).
- **Bronze module** — designed (`docs/bronze-design.md`), contracts pinned,
  tests written, implementation complete. Code review in progress.
- **Bronze parquet on disk** — produced for all extraction-complete years.
  Manifest written.
- **Terraform scaffold + GCS bucket** — `terraform/` provisions
  `openalex-pipeline-bronze` (EU, UBLA, public-access prevention), GCS backend
  for state, SA impersonation.
- **Upload module** — designed (`docs/upload-design.md`), contracts pinned,
  tested, implementation complete (`python -m openalex_pipeline.upload`).
  Uploads bronze parquet to GCS Hive-partitioned for BigQuery; derived upload
  manifest at `gs://{bucket}/upload/_MANIFEST.parquet`. Code review pending.
- **Bronze parquet in GCS** — all 77 years (1950–2026) uploaded to
  `gs://openalex-pipeline-bronze/bronze/publication_year=YYYY/YYYY.parquet`
  (~4.6 GB). Manifest written and verified: 77 rows, sizes match local files
  exactly. Re-run is fully idempotent (skips all 77).
- **Warehouse foundation design** — `docs/staging-design.md` covers Terraform
  datasets, the bronze external table, dbt init, and the staging model.
  External-vs-native answered: external table as dbt source, native from
  staging onward.
- **BigQuery datasets + bronze external table** — Terraform provisions
  `openalex_raw` (external table), `openalex_analytics` (dbt prod),
  `openalex_analytics_dev` (dbt dev), all in `EU`. External table
  `openalex_raw.bronze_external` over the GCS parquet, CUSTOM Hive
  partitioning, pinned 20-column schema (+ `publication_year` from the
  partition key; `ignore_changes = [schema]` suppresses the API's appended
  partition column, which would otherwise force-replace every plan). Gate
  verified: 77 years, single `INT64` `publication_year`, per-year counts match
  `bronze_row_count` in the manifest exactly (14,775,131 rows). Partition
  pruning confirmed via bytes-billed (decade slice ≈ 7.8 MB vs 118 MB full
  scan on one column). Terraform refactored into per-concern files
  (`versions/providers/variables/storage/bigquery/outputs.tf`).
- **Extraction + bronze hardening (post-review)** — empty-pagefile contract
  closed (`EmptyPageAnomaly`; only a zero-result year's page-0001 may be
  zero-byte). fsync added to extraction's atomic write (torn-page-after-
  power-loss was the one corruption the resume protocol couldn't see).
  Landing-zone rule pinned in `DATA_MODEL.md` (one zone = one query) and
  enforced: bronze asserts query homogeneity across shards before ingesting,
  and the manifest re-asserts `records_fetched == bronze_row_count` on every
  rebuild (catches stale parquet after a re-extraction). 403-vs-429 semantics
  (burst limit vs daily cap, empirically verified) documented in the
  connector/exceptions.

- **dbt project init** (`docs/staging-design.md` §3) — implemented, **pending
  review** (not yet committed; Nils commits after review). dbt added as a main
  dep (`dbt-core`/`dbt-bigquery`, BigQuery adapter); `google-cloud-storage`
  floor relaxed to `>=3.1.1` to clear dbt-bigquery's `<3.2` cap (resolves to
  3.1.1, fine for the upload module). dbt identity: dedicated `dbt-runner` SA,
  impersonated via the caller's ADC (mirrors the terraform-runner pattern) —
  Terraform `iam.tf` adds the SA + least-privilege grants (project jobUser;
  dataEditor on the two analytics datasets; dataViewer on raw; objectViewer on
  the bronze bucket; tokenCreator for the developer's principal). **IAM
  applied** via the `-out` flow. `/dbt/` skeleton: `dbt_project.yml` (staging
  `+materialized: table`, corpus-bounds vars 1950–2026), `profiles.yml` (dev
  default / prod opt-in, both EU, both threads 4, SA impersonation),
  `models/staging/_sources.yml` (`bronze_external`). `DBT_PROFILES_DIR=dbt` in
  `.env`/`.env.example`. `dbt parse` clean. The `dbt_impersonator` value lives
  in a gitignored `terraform.tfvars`; the var has no default and is
  `sensitive = true` (no personal email in tracked files or history).

- **dbt staging `stg_works` + connectivity gate** (`PLAN.md` steps 4–5) —
  implemented, **pending review** (not committed). `dbt_utils` added
  (`dbt/packages.yml`, v1.4.0; `package-lock.yml` committed). Step 4: `dbt debug`
  green; smoke model ran against dev (exercised oauth→impersonation→external
  read→bucket grant→write), then deleted. Step 5: `stg_works` (`models/staging/`)
  parses all 8 JSON columns (flattened scalars + typed nested arrays for
  `topics`/`counts_by_year`/`keywords`), SAFE-types the two dates, applies the
  `is_retracted`/`is_paratext` + corpus-bounds filters, dedups on `id` via
  `QUALIFY` (latest `updated_date`, `nulls last`). Config: `materialized=table`,
  integer-range partition on `publication_year` (1950–2026), cluster on
  `primary_topic_subfield_id`. Tests: `_staging.yml` (`id` not_null/unique,
  `publication_year` not_null + `accepted_range`, `primary_topic_subfield_id`
  not_null at **warn**) + two singular source date-parse tests. Verified on the
  1991–2000 dev slice: 975,478 rows, **all 7 tests green**, **2.80 GiB billed**
  (confirms partition pruning — a full unpruned scan bills 40+ GiB; the gap is
  compression: GCS stores compressed Parquet ~10×, BigQuery bills uncompressed).
  - *Known gap:* the two singular tests scan the `source` (not `ref`), so
    `--select stg_works` does **not** include them; they run under a bare
    `dbt build`/`dbt test`. Flagged for review — leave as-is or rewire to the
    model graph.

- **Prod run + reconcile** (`PLAN.md` step 6) — **done**, pending review. Added a
  per-job `maximum_bytes_billed` cap (100 GiB) to **both** profile targets (not
  cumulative — sized to clear the single biggest job, the full external scan; a
  daily ceiling would be a GCP custom quota, not this). Full `dbt build -t prod`
  (no selector, so the singular tests ran): `stg_works` = **14,723,333 rows**,
  **43.2 GiB billed** (under cap), **all 8 nodes green**. Reconciliation against
  the manifest **balances exactly**:
  `14,775,131 (manifest) − 50,480 (is_retracted OR is_paratext = TRUE) − 1,282
  (is_retracted NULL, intentionally dropped) − 36 (dedup) = 14,723,333`.
  - *NULL quality flags (decided):* `is_retracted` is NULL for 6,025 works
    (`is_paratext` never NULL); 1,282 of those are dropped **solely** by the
    `= false` filter (NULL = false → excluded). Decision: **drop, made explicit**
    — comment in `stg_works.sql` documents the conservative exclusion of
    unrecorded-status works (~0.009%, scattered across years, not old-corpus).
    No rebuild needed (behavior unchanged; comment-only edit).
  - *Subfield test:* `primary_topic_subfield_id` had **0 nulls** across the full
    corpus, but kept at **warn** (deliberate — defer the hard primary_topic-less
    decision to the silver design, which must handle it regardless).

- **dbt silver `silver_works`** (`PLAN.md` step 7, `docs/silver-design.md`) —
  designed, implemented, built on prod, **pending review**. One model, one row
  per work (`ref('stg_works')`, no filter): adds `is_ai_strict` / `is_ai_broad`
  (coalesced-boolean, matched on the pinned `subfield_ai` `1702` / `subfield_cv_pr`
  `1707` vars) and projects staging to the analytical columns; `counts_by_year`
  carried nested for gold's half-life. Config mirrors staging (`table`, int-range
  partition on `publication_year`, cluster on subfield). Tests (`_silver.yml` +
  singular): `id` not_null/unique, flags not_null, the `ai_strict ⊆ ai_broad`
  subset invariant, two classification-correctness assertions, and a singular
  row-count test (silver == staging). **Prod: all green**, 14,723,333 rows
  (== staging), `ai_strict` **27.49%** (4,047,312) / `ai_broad` **40.01%**
  (5,891,425) — on the anchor; `strict_not_broad = 0` in the data. `DATA_MODEL.md`
  carries the exact subfield ids.
  - *Log path fixed:* the deprecated `log-path` in `dbt_project.yml` (added to
    stop dbt dropping `logs/` at the repo root — the log path is CWD-relative,
    not `--project-dir`-relative) is replaced by `DBT_LOG_PATH=dbt/logs` in
    `.env`/`.env.example`. Deprecation gone; logs land in `dbt/logs/`.

- **Dev slice moved to 2012–2016** (was 1991–2000). The old decade slice
  predates the `counts_by_year` finding and is useless for gold (no citation
  data before 2012). The canonical dev slice now equals the Q2/Q3 analytical
  cohort — one slice for all layers, dev gold previews prod numbers. 2.68 M
  rows (18.1% of corpus, per the bronze manifest), ~8 GiB per full dev rebuild
  (extrapolated from the measured 2.80 GiB / 978 k-row staging anchor).
  Convention updated in `dbt_project.yml` + `PLAN.md`; dev dataset rebuilt on
  the new slice (full `dbt build`, 47/47 green).

- **dbt gold** (`PLAN.md` step 8, `docs/gold-design.md` — **design approved**,
  §6 decisions: 1–4 as recommended, 5 = flag column kept) — implemented, built
  on dev **and prod**, **pending review** (not committed). Four models in
  `models/gold/` (`+materialized: table`, no partitioning — tiny outputs):
  `gold_ai_share_by_year` (Q1; long over strict/broad, `is_partial_year` on
  2026 via `partial_year` var), `int_paper_half_life` (view; per-cited-paper
  cumulative-to-50% half-life, linear interpolation, `age < 0` dropped,
  first-observation crossing snaps), `gold_citation_half_life_by_subfield`
  (Q2; exact `percentile_cont` p25/median/p75 + `n_cited`/`uncited_rate`
  context), `gold_citation_gini_by_subfield` (Q3; single-window-pass Gini,
  zeros included, `nullif` guard). Q2/Q3 cohort = vars
  `half_life_cohort_min/max` (2012–2016). Tests: `_gold.yml` (uniqueness,
  bounds: share/gini/uncited_rate ∈ [0,1], half-life > 0, n_cited ≤ n_papers,
  ai_works ≤ cs_works, variant accepted_values) + two singular
  (strict-share ≤ broad-share per year; AI subfield present in both
  subfield-grain tables). **Prod: 30/30 green.** Sanity (unweighted subfield-
  median averages, AI vs rest): Gini 0.898 vs 0.874 (strict) — AI slightly
  more concentrated; half-life ≈ 3.5 vs 3.5 — no aging gap at first glance.
  Q1 share is **not monotone**: ~30% strict in 1980, dip to ~23% in 2012,
  rise to ~40% in 2026 (partial) — consistent with the AI-winters narrative
  (Nils), worth a dashboard note. Strict ≤ broad holds everywhere; 2026
  flagged partial.
  - *`gini_cited_only` secondary added* (design §4c option, requested at
    review): same formula over cited papers only, plus the
    `gini_cited_only <= gini` invariant test (adding zeros can only raise
    concentration). **Finding: the two ginis rank subfields differently.**
    All-papers leader Information Systems (0.929, but 71% uncited) drops to
    mid-pack cited-only (0.761), while **AI (0.797) and CV/PR (0.823) are the
    top two cited-only ginis** — with *below-average* uncited rates (50%/40%).
    The Winner's-Game story sharpens: AI's concentration is among papers that
    do get cited, not an artifact of uncited mass. Rebuilt dev + prod, 9/9
    green each.

## Next

(Steps per `PLAN.md`; staging/silver committed; gold done on prod, pending
review + commit.)

9. Dagster orchestration — **designed, implemented, and review-round-3 fixes
   applied (2026-07-17); ready for Nils's review.** Supersedes the
   2026-07-07 scope note: full asset graph (unpartitioned wrappers over the
   existing runners + `dagster-dbt`, Dagster log advisory-only), a **daily
   `local_sweep`** (bootstrap and refresh are the same converging job), a
   **monthly invalidation request** for the current year (durable tombstone +
   sweep-owned executor), and a
   **staleness sensor** gating the prod dbt rebuild on
   converged-∧-warehouse-stale, derived purely from FS/GCS/BQ metadata.
   Automation boundary revised: manual full backfill, automated refresh
   (`ARCHITECTURE.md`, `README.md`, `.env.example` updated). Review round 1
   (2026-07-09) applied: staleness
   predicate hardened to min-last_modified over **all** dbt-managed tables
   (single-sentinel `stg_works` flips not-stale after a partial build);
   convergence pinned to `classify_year` + `canonical_query` (adds query-
   homogeneity assertion). Same review logged a **gold known gap**
   (`docs/gold-design.md` §9): pooled AI-vs-rest is not derivable from the
   subfield-grain gold tables (medians/Ginis don't compose) — deferred to the
   Q2/Q3 revisit; dashboard must stay subfield-comparison-only until then.
   Implementation added `src/openalex_pipeline/orchestration/` with
   filesystem/GCS/BQ predicates, Dagster assets/jobs/schedules/sensor, and
   tests in `tests/orchestration/`. Review round 2 (PLAN F0–F9) is closed:
   canonical tracked `dagster.yaml` with bounded automatic retries; absolute
   direnv-bootstrapped `DAGSTER_HOME`; interruption-safe request/executor
   invalidation tombstones; exclusive writer/shared sensor filesystem locking;
   strict upload-manifest completeness/schema validation; separate table/view
   existence and table-freshness contracts; import-time serialized prod dbt
   manifest preparation that works from a clean checkout; all automations
   default RUNNING; and honest per-run asset metadata with wrapper/sensor/lock
   coverage. Bare Dagster launch is pinned through `[tool.dagster]`. Review
   round 3 closed one remaining tombstone-validation hole: symlinks are now
   rejected as corruption before they can authorize deletion.
   Verification: full pytest **218 passed**, repo-wide Ruff lint clean, touched
   paths Ruff-format and Pyright clean, clean-checkout subprocess green,
   `dagster definitions validate` green, real instance config shows retries
   enabled, and a production smoke loaded the end-to-end code location and
   daemon successfully. Real sensor preflight and smoke both reported
   `warehouse is fresh`; no warehouse build or local sweep launched.
10. Streamlit dashboard.
