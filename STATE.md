# STATE.md

*Last updated: 2026-07-17*

This file records current repository and deployed-pipeline state. Completed
implementation history belongs in git and archived design docs, not here.

## Approved and complete

All implemented modules have been reviewed and approved.

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
- **dbt gold** — four models implement annual AI share, per-paper citation
  half-life, subfield half-life summaries, and subfield citation Gini. The Q2
  and Q3 cohort is 2012–2016; headline Gini includes uncited papers and the
  secondary `gini_cited_only` separates concentration among cited papers.
- **Dagster orchestration** — the end-to-end asset graph, daily local sweep,
  monthly current-year invalidation request, and warehouse staleness sensor are
  implemented and tested. Filesystem/GCS/BigQuery state remains authoritative;
  Dagster history is advisory. Invalidation is interruption-safe, local access
  is serialized with filesystem locks, warehouse retries are bounded, dbt
  manifest preparation works from a clean checkout, and all three automations
  default to running.

Completed extraction-through-gold designs are archived under
`docs/design-archive/`. `docs/orchestration-design.md` remains the active
orchestration contract.

## Operational and data snapshot

- The extraction and upload corpus covers 77 publication-year shards
  (1950–2026), with 2026 partial.
- The bronze manifest reconciles to **14,775,131** extracted rows. The prod
  staging and silver tables contain **14,723,333** rows after the documented
  retraction/paratext, null-status, and deduplication rules.
- Prod dbt has been built successfully and its tests pass. The last recorded
  full staging build billed 43.2 GiB, below the configured 100 GiB per-job cap.
- The canonical dev slice is 2012–2016, matching the current Q2/Q3 cohort.
- The latest repository verification is **218 pytest tests passed**, with Ruff,
  Ruff format, Pyright on the orchestration paths, Dagster definitions
  validation, and the real instance retry configuration all green.
- The latest live orchestration preflight reported `warehouse is fresh`; it
  launched neither a local sweep nor a warehouse build.

## Known limitations

- **Dashboard not implemented.** Streamlit is the remaining application layer.
- **Q2/Q3 do not yet publish pooled AI-vs-rest statistics.** Their gold outputs
  are one row per CS subfield with strict/broad classification flags. Subfield
  medians and Ginis cannot be pooled downstream; pooled metrics require new
  paper-level aggregations.
- **Q2/Q3 source freshness is not automated.** The refresh automation currently
  invalidates only the current-year shard, while the 2012–2016 cohort's
  `counts_by_year` values can continue changing at OpenAlex.
- **Year rollover is manual.** Advancing the corpus requires coordinated
  updates to extraction bounds and dbt vars.

## Current work

See `PLAN.md`. The next decision is whether to close the Q2/Q3 analytical and
refresh gaps before designing the dashboard. Recommendation: close them first
so the dashboard is built against final, honestly refreshable gold contracts.
