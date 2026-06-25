# STATE.md

*Last updated: 2026-06-25*

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

## Next

(Steps per `PLAN.md`; staging steps 4–6 done, pending review. The whole dbt
staging layer is now built on prod and reconciled.)

7. dbt silver: AI classification (`ai_strict` and `ai_broad` ablations),
   field flattening. **Design drafted** — `docs/silver-design.md`, pending
   review. Resolves the staging §7 open questions: match on subfield **id**
   (AI `1702`, CV/PR `1707`, pinned as `dbt_project.yml` vars `subfield_ai` /
   `subfield_cv_pr`); two coalesced-boolean flags on the work row (`ai_strict ⊆
   ai_broad`, tested); null-subfield → non-AI, kept in CS denominator (0 nulls
   at full corpus anyway); `counts_by_year` stays nested, reshaped in gold.
   Measured anchor: `ai_strict` ≈27.5%, `ai_broad` ≈40.0% of CS. `DATA_MODEL.md`
   updated with the exact subfield ids + that matching is by id. Next: implement
   `silver_works` per the doc.
8. dbt gold: aggregates answering Q1/Q2/Q3 (subfield share, citation
   half-life, Gini coefficient). Needs its own design doc (half-life definition,
   Gini formulation, the `counts_by_year` long reshape).
9. Dagster orchestration: wire extraction, bronze, and dbt as
   software-defined assets.
10. Streamlit dashboard.
