# STATE.md

*Last updated: 2026-06-06*

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

## In Progress

- **Bronze code review** — manual line-by-line review. Running in
  parallel with downstream planning so nothing blocks on it.

## Next

1. Upload code review.
2. BigQuery external tables over GCS parquet. This is where the
   external-vs-native question gets answered.
3. dbt project init against BigQuery. Dev target on a small dataset (1–2
   years) for fast iteration; prod target on the full corpus.
4. dbt staging: parse the eight nested JSON-string columns; apply data
   quality filters.
5. dbt silver: AI classification (`ai_strict` and `ai_broad` ablations),
   field flattening for the analytical questions.
6. dbt gold: aggregates answering Q1/Q2/Q3 (subfield share, citation
   half-life, Gini coefficient).
7. Dagster orchestration: wire extraction, bronze, and dbt as
   software-defined assets.
8. Streamlit dashboard.

Items 1–2 are mostly mechanical and parallelizable with bronze code review.
Item 3 is the next genuinely-designed step.