# STATE.md

*Last updated: 2026-07-29*

This file records current repository and deployed-pipeline state. Completed
implementation history belongs in git and archived design docs, not here.

## Approved and complete

All previously retained implementation has been reviewed and approved. The new
Q2 implementation is locally verified and awaits project review and deployment.

- **Extraction** — the resumable OpenAlex API pull is implemented, tested, and
  deployed locally. Years 1950–2025 are complete; 2026 is intentionally
  partial and is the automated refresh target. Extraction reports on disk are
  the completion signals.
- **Bronze** — JSONL-to-Parquet ingestion, pinned schema enforcement, query
  homogeneity, count reconciliation, atomic writes, and the derived local
  manifest are implemented and tested. Parquet exists for every
  extraction-complete year.
- **Upload** — idempotent local-Parquet-to-GCS upload is implemented and
  tested. Objects use the Hive path
  `bronze/publication_year=YYYY/YYYY.parquet`; the strict derived upload
  manifest lives at `upload/_MANIFEST.parquet`.
- **Cloud foundation** — Terraform provisions the EU GCS bucket, BigQuery raw,
  prod, and dev datasets, the Hive-partitioned bronze external table, service
  accounts, and least-privilege IAM. The infrastructure has been applied.
- **dbt staging** — `stg_works` parses the eight JSON-string fields, types
  dates and nested data, applies the documented quality filters, deduplicates
  by work id, and materializes as a partitioned and clustered native BigQuery
  table.
- **dbt silver** — `silver_works` preserves staging grain and adds the pinned
  `ai_strict` and `ai_broad` classifications. Classification, subset, key, and
  row-count invariants are tested.
- **dbt gold, retained contracts** — Q1 implements annual strict/broad AI
  share. Q3 implements subfield citation Gini over the 2012–2016 cohort;
  headline Gini includes uncited papers and the secondary
  `gini_cited_only` separates concentration among cited papers.
- **Dagster orchestration** — the end-to-end asset graph, daily local sweep,
  monthly current-year invalidation request, and warehouse staleness sensor are
  implemented and tested. Filesystem/GCS/BigQuery state remains authoritative;
  Dagster history is advisory. Invalidation is interruption-safe, local access
  is serialized with filesystem locks, warehouse retries are bounded, dbt
  manifest preparation works from a clean checkout, and all three automations
  default to running.
- **Local data configuration** — `OPENALEX_DATA_ROOT` is the sole local data
  location. Extraction and bronze derive `extract/` and `bronze/` beneath it,
  and the orchestration lock remains at the root. Implemented, tested, and
  approved.

Completed baseline designs are archived under `docs/design-archive/`.
`docs/gold-revisit-design.md` is the reviewed and approved Q2 implementation
contract. `docs/orchestration-design.md` remains the active orchestration
contract.

## Operational and data snapshot

- The extraction and upload corpus covers 77 publication-year shards
  (1950–2026), with 2026 partial.
- The bronze manifest reconciles to **14,775,131** extracted rows. The prod
  staging and silver tables contain **14,723,333** rows after the documented
  retraction/paratext, null-status, and deduplication rules.
- Prod dbt has been built successfully and its tests pass. The last recorded
  full staging build billed 43.2 GiB, below the configured 100 GiB per-job cap.
- The canonical dev slice is 2012–2016, matching the Q3 cohort. It is a
  structural development target for Q2, not an analytical preview of prod Q2.
- The latest repository verification is **220 pytest tests passed**, with Ruff,
  Ruff format, Pyright on the touched Python paths, Dagster definitions
  validation, and the real instance retry configuration all green.
- The local Q2 implementation parses and compiles offline with **5 dbt models
  and 60 data tests**. Its manifest contains `gold_citation_age_by_year` and
  neither obsolete Q2 relation.
- The latest live orchestration preflight reported `warehouse is fresh`; it
  launched neither a local sweep nor a warehouse build.

## Known limitations

- **Dashboard not implemented.** Streamlit is the remaining application layer.
- **Q2 replacement not deployed.** `gold_citation_age_by_year` is implemented
  and locally verified against the approved AI/CV-PR/rest-of-CS contract. Dev
  and prod builds, prod reconciliation, analytical inspection, and obsolete
  relation cleanup remain.
- **Q2 is snapshot-scoped by decision.** It will publish citation years
  2012–2025 from the current full-corpus snapshot. Extending the range requires
  a manual full-corpus refresh; monthly current-year invalidation is not a Q2
  freshness guarantee.
- **Q3 does not publish pooled AI-vs-rest statistics.** Its output is one row
  per CS subfield with strict/broad classification flags. Subfield Ginis
  cannot be pooled downstream; a pooled metric requires a direct paper-level
  aggregation.
- **Q3 source freshness is not automated.** The current-year-only refresh does
  not update cumulative citation counts on the 2012–2016 publication cohort.
- **Year rollover is manual.** Advancing the corpus requires coordinated
  updates to extraction bounds and dbt vars.

## Current work

See `PLAN.md`. Q2's analytical, grouping, model, test, removal, and freshness
contracts are reviewed and approved; local implementation is ready for project
review. Deployment and prod reconciliation follow that review. Q3's pooled
comparison remains a separate decision. Dashboard design waits for final gold
contracts.
