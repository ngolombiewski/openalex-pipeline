# STATE.md

*Last updated: 2026-06-12*

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

## Next

(Steps per `docs/staging-design.md` §6; 1–2 are done.)

3. dbt project init against BigQuery: profiles (dev default / prod opt-in),
   source declaration, corpus-bounds vars (`year_min`/`year_max`; dev uses a
   mid-corpus decade slice like 1991–2000).
4. Sanity-query the source through dbt; confirm pruning end-to-end.
5. dbt staging `stg_works`: parse the eight nested JSON-string columns, type
   dates, quality filters, dedup on `id` (≥1 known duplicate). Tests.
6. Prod run + reconcile counts against the manifest.
7. dbt silver: AI classification (`ai_strict` and `ai_broad` ablations),
   field flattening for the analytical questions.
8. dbt gold: aggregates answering Q1/Q2/Q3 (subfield share, citation
   half-life, Gini coefficient).
9. Dagster orchestration: wire extraction, bronze, and dbt as
   software-defined assets.
10. Streamlit dashboard.

Silver (7) is the next step that needs a design doc before implementation.
