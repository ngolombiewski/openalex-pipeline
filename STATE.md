# STATE.md

*Last updated: 2026-06-05*

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

## In Progress

- **Bronze code review** — manual line-by-line review. Running in
  parallel with downstream planning so nothing blocks on it.

## Next

1. GCP account housekeeping: free → paid tier, billing alerts, project
   setup.
2. Terraform: design what to provision (GCS bucket, BigQuery dataset,
   service account, IAM), then write the HCL.
3. Upload bronze parquet to GCS. One-shot at first; the upload step's
   permanent home (separate stage vs. orchestration concern) is open.
4. BigQuery external tables over GCS parquet. This is where the
   external-vs-native question gets answered.
5. dbt project init against BigQuery. Dev target on a small dataset (1–2
   years) for fast iteration; prod target on the full corpus.
6. dbt staging: parse the eight nested JSON-string columns; apply data
   quality filters.
7. dbt silver: AI classification (`ai_strict` and `ai_broad` ablations),
   field flattening for the analytical questions.
8. dbt gold: aggregates answering Q1/Q2/Q3 (subfield share, citation
   half-life, Gini coefficient).
9. Dagster orchestration: wire extraction, bronze, and dbt as
   software-defined assets.
10. Streamlit dashboard.

Items 1–4 are mostly mechanical and parallelizable with bronze code review.
Item 5 is the next genuinely-designed step.