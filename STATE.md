# STATE.md

*Last updated: 2026-07-31*

This file records current repository and deployed-pipeline state. Completed
implementation history belongs in git and archived design docs, not here.

## Approved and complete

All previously retained implementation has been reviewed and approved. The new
Q2 implementation is deployed and prod-reconciled; its deployed result awaits
project review.

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
- **dbt gold, Q2 replacement** — `gold_citation_age_by_year` publishes annual
  citation-weighted age distributions for the exclusive AI, CV/PR, and
  rest-of-CS cited-work groups over citation years 2012–2025. It is deployed
  and tested in dev and prod. The superseded half-life table and intermediate
  view have been removed from both datasets.
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
`docs/gold-q2-revisit-design.md` is the reviewed and approved Q2 implementation
contract. `docs/orchestration-design.md` remains the active orchestration
contract.

## Implemented, awaiting review and prod deployment

- **dbt gold, Q3 replacement** — the approved fixed-window cohort-series
  contract in `docs/gold-q3-revisit-design.md` is implemented. The primary
  `gold_citation_gini_by_subfield` relation is replaced in code at
  `subfield_id × publication_year × citation_age`; the secondary directly
  pooled `gold_citation_gini_by_group` relation adds the exclusive
  `ai` / `cv_pr` / `rest_cs` lens. Both publish overall and cited-only Ginis,
  zero share, top-1/5/10 shares, and age-0 diagnostics over complete
  post-publication calendar-year windows. Contracts, deterministic metric
  fixtures, independent source oracles, and cross-grain invariants are in
  place. The canonical dev build and test suite pass. Prod still serves the
  approved cumulative-count Q3 until review and the required prod
  reconciliation complete.

## Operational and data snapshot

- The extraction and upload corpus covers 77 publication-year shards
  (1950–2026), with 2026 partial.
- The bronze manifest reconciles to **14,775,131** extracted rows. The prod
  staging and silver tables contain **14,723,333** rows after the documented
  retraction/paratext, null-status, and deduplication rules.
- Prod dbt has been built successfully and its tests pass. The last recorded
  full staging build billed 43.2 GiB, below the configured 100 GiB per-job cap.
- The canonical dev slice is 2012–2016. It now publishes the exact
  overlapping-cohort preview of the Q3 replacement: **605 subfield rows** and
  **165 pooled-group rows**, with cohort 2012 reaching citation age 13 and
  cohort 2016 reaching age 9. It remains a structural development target for
  Q2, not an analytical preview of prod Q2.
- The latest Python/Dagster regression verification is **247 pytest tests
  passed**, including Dagster definitions validation and the real instance
  retry configuration; Ruff check also passes. No Python was changed for Q3.
  The repo-wide Ruff format check still identifies 19 pre-existing files and
  was not applied because they are outside this change.
- The repository dbt manifest contains **6 models, 110 data tests, and 3
  deterministic unit tests**. The two Q3 dev models billed 366.8 MiB processed
  each. Their focused build passed 61 executed checks, and the complete dev
  suite passed **112 checks with one expected warning** across 110 data tests
  and 3 unit tests. The shared negative-age warning returned 46,357 dev rows.
- Q3 display-label preflights found **zero conflicting labels and zero
  fallbacks** in both dev and prod silver; the built dev output has zero
  unstable real-subfield labels.
- Prod Q2 contains exactly **42 rows**: three groups for every citation year
  from 2012 through 2025, with no 2026 row. Citation-event and distinct-work
  totals reconcile exactly to an independent eligible silver aggregation for
  every year; every recorded delta is zero.
- Prod validation excluded **198,882** positive negative-age entries carrying
  **779,220** citation events (about 0.70% of eligible-plus-excluded event
  weight). The anomalies decline from 25,065 entries in 2012 to 818 in 2025;
  their ages span -14 through -1.
- Median citation age trends younger in all three groups. AI moves from 8 years
  in 2012 to 5 in 2023–2025; CV/PR moves from 7 to 5 by 2018; rest of CS moves
  from 7 to 5 by 2022. In 2025 the shares of citation events to works aged at
  most five years are 55.4% for AI, 57.2% for CV/PR, and 54.3% for rest of CS.
- Q2 prod query costs remained far below the 100 GiB per-job cap:

  | Job | Bytes processed | Bytes billed |
  |---|---:|---:|
  | `gold_citation_age_by_year` | 1,547,972,704 | 1,548,746,752 |
  | `assert_citation_age_source_valid` | 885,422,719 | 886,046,720 |
  | `assert_gold_citation_age_events_reconcile` | 1,048,516,361 | 1,048,576,000 |
  | `assert_gold_citation_age_cited_works_reconcile` | 1,547,973,656 | 1,548,746,752 |
  | `warn_citation_age_negative_entries` | 503,752,088 | 504,365,056 |
- The latest live orchestration preflight reported `warehouse is fresh`; it
  launched neither a local sweep nor a warehouse build.

## Known limitations

- **Dashboard not implemented.** Streamlit is the remaining application layer.
- **Q2 is snapshot-scoped by decision.** It publishes citation years
  2012–2025 from the current full-corpus snapshot. Extending the range requires
  a manual full-corpus refresh; monthly current-year invalidation is not a Q2
  freshness guarantee.
- **Prod Q3 does not yet publish pooled AI-vs-rest statistics.** The
  replacement is implemented and tested in dev, including the directly
  computed pooled relation, but prod remains on the approved subfield-only
  cumulative contract pending review and reconciliation.
- **Q3 source freshness is not automated.** The current-year-only refresh does
  not update historical citation windows or classifications. Even after the
  replacement is deployed, Q3 remains a full-corpus analytical snapshot.
- **Year rollover is manual.** Advancing the corpus requires coordinated
  updates to extraction bounds and dbt vars.

## Current work

See `PLAN.md`. Q2's implementation, deployment, prod reconciliation,
analytical inspection, obsolete-relation cleanup, and orchestration validation
are complete; the deployed result awaits project review. Q3's fixed-window
cohort-series replacement, including the secondary pooled comparison, is
implemented and dev-validated. Implementation review, prod deployment, the
full §9d analytical reconciliation, and post-deployment documentation remain.
Dashboard design waits for final deployed gold contracts.
