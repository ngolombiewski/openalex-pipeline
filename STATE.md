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
  share.
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

## Deployed, awaiting review

- **dbt gold, Q3 replacement** — the approved fixed-window cohort-series
  contract in `docs/gold-q3-revisit-design.md` is implemented and deployed to
  prod. The primary `gold_citation_gini_by_subfield` relation is replaced at
  `subfield_id × publication_year × citation_age`; the secondary directly
  pooled `gold_citation_gini_by_group` relation adds the exclusive
  `ai` / `cv_pr` / `rest_cs` lens. Both publish overall and cited-only Ginis,
  zero share, top-1/5/10 shares, and age-0 diagnostics over complete
  post-publication calendar-year windows. Contracts, deterministic metric
  fixtures, independent source oracles, and cross-grain invariants are in
  place. The complete §9d reconciliation is done; results are below. The
  superseded cumulative-count Q3 no longer exists in either dataset. Only
  Nils's implementation review remains.

## Operational and data snapshot

- The extraction and upload corpus covers 77 publication-year shards
  (1950–2026), with 2026 partial.
- The bronze manifest reconciles to **14,775,131** extracted rows. The prod
  staging and silver tables contain **14,723,333** rows after the documented
  retraction/paratext, null-status, and deduplication rules.
- Prod dbt has been built successfully and its tests pass. The last recorded
  full staging build billed 43.2 GiB, below the configured 100 GiB per-job cap.
- The canonical dev slice is 2012–2016. It publishes the overlapping-cohort
  preview of the Q3 replacement: **605 subfield rows** and **165 pooled-group
  rows**, with cohort 2012 reaching citation age 13 and cohort 2016 reaching
  age 9. It remains a structural development target for Q2, not an analytical
  preview of prod Q2.
- The latest Python/Dagster regression verification is **247 pytest tests
  passed**, including Dagster definitions validation and the real instance
  retry configuration; Ruff check also passes. No Python was changed for Q3.
  The repo-wide Ruff format check still identifies 19 pre-existing files and
  was not applied because they are outside this change.
- The repository dbt manifest contains **6 models, 110 data tests, and 3
  deterministic unit tests**. The complete suite passes in both targets:
  **112 checks with one expected warning** each. The shared negative-age
  warning returned 198,882 prod rows and 46,357 dev rows.
- Q3 display-label preflights found **zero conflicting labels and zero
  fallbacks** in both dev and prod silver; every published real subfield in
  both built outputs carries one stable non-null label.
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
- Prod Q3 publishes the complete observable triangle `[2012, 2024] ×
  [1, 2025 - y]` — **91 cohort/age cells**, giving **1,001 subfield rows** and
  **273 pooled-group rows**. No interior cell is absent and nothing lies beyond
  the configured edge at either grain.
- Q3 §9d reconciliation passed at both grains: zero cross-grain sum
  mismatches across all 91 cells, zero violations of the
  `G = p + (1-p)·G_cond` decomposition across every published row, and exact
  agreement with the independent per-cell source oracles. The
  `__unclassified__` bucket is empty — prod silver has no null-subfield paper,
  so the bucket is defensive only.
- The **dev/prod overlap reconciles under the §9d.11 tolerance, not exactly**.
  All 605 keys match with zero classification-flag deltas, but 96 cells carry
  nonzero integer deltas and ratios differ by up to 2.7e-5. The cause is the
  §8 slice-boundary dedup: dev `stg_works` holds **12 more works** in
  2012–2016 than prod (2,668,938 vs 2,668,926). All 12 exist in prod under a
  later publication year — 11 under 2026 and one under 2017 — because
  `stg_works` keeps the freshest snapshot after applying the year filter.
  Prod is correct; the difference is 4.5e-6 of the slice and fully accounts
  for every observed delta.
- Q3 age-0 sensitivity is **substantively neutral**. Including age 0 moves
  subfield Gini by a mean of -0.0055 at window 3 and -0.0042 at window 5
  (range -0.0107 to -0.0015); top-k shares move by at most 0.017. AI holds
  rank **3–5 of 11** in every cohort under both variants, with only two
  one-position swaps across 20 cohort/window cases. The pooled AI-vs-rest
  comparison shows **zero sign reversals** in 20 comparisons.
- Q3 age-0 diagnostics are group-differentiated but small. Mean
  `age0_citation_share` at windows 3 and 5 is 8.1% / 4.7% for AI, 5.9% / 3.4%
  for CV/PR, and 7.9% / 4.8% for rest of CS. The mean `zero_share` gap is
  1.7–2.0% at window 3 and 1.2–1.4% at window 5.
- Inside the Q3 cohort range, **192,150** negative-age entries carry
  **717,886** citation events spanning ages -12 through -1, about 1.1% of the
  cohorts' recorded event weight. The ages-1..N window excludes them.
- The **terminal-edge diagnostic does not justify retreating to 2024**. At
  window 3 the terminal 2022 cohort moves -0.013 / -0.010 / -0.006 in Gini
  against 2021; at window 5 the terminal 2020 cohort moves -0.005 / -0.004 /
  **+0.003** against 2019. The direction contradicts under-indexing: the
  terminal cohorts show *higher* citations per paper and *lower* zero shares.
  Across the whole 2025-ending diagonal the cohort steps are indistinguishable
  from the interior (mean -0.0018, sd 0.0156 versus -0.0012, sd 0.0120).
  `gini_citation_year_max` stays at 2025.
- Q3 cohort series carry no structural discontinuity. The largest steps sit in
  the smallest subfields at the shortest windows — Software at 4,859 papers
  moves +0.079 at age 2 — and the window-5 series are smoother than window-3
  throughout.
- AI is never the most concentrated CS subfield. It ranks 3rd to 5th of 11 in
  every cohort at both windows, sitting 0.40–0.76 into the min–max spread;
  Information Systems holds the maximum throughout. Pooled `rest_cs` Gini
  exceeds the mean individual-subfield Gini because pooling heterogeneous
  subfields adds between-subfield inequality — the §4b asymmetry, measured.
- Q3 prod query costs were far below the 100 GiB per-job cap. The maximum
  single job processed **1,072,844,491 bytes**; the whole 61-job build and
  test run processed 4.39 GB:

  | Job | Bytes processed | Bytes billed |
  |---|---:|---:|
  | `gold_citation_gini_by_subfield` | 1,072,844,491 | 1,073,741,824 |
  | `gold_citation_gini_by_group` | 1,072,844,491 | 1,073,741,824 |
  | `assert_gold_citation_gini_subfield_source_reconcile` | 833,377,502 | 833,617,920 |
  | `assert_gold_citation_gini_group_source_reconcile` | 833,301,517 | 833,617,920 |
  | `assert_gold_citation_gini_subfield_labels` | 574,254,963 | 574,619,648 |
- A manifest parse from a deleted-manifest state maps all **6 models**,
  including the new `gold_citation_gini_by_group`, with no stale half-life or
  intermediate relation. The latest live orchestration preflight found every
  expected relation present in prod and reported `warehouse is fresh`; it
  launched neither a local sweep nor a warehouse build.

## Known limitations

- **Dashboard not implemented.** Streamlit is the remaining application layer.
- **Q2 is snapshot-scoped by decision.** It publishes citation years
  2012–2025 from the current full-corpus snapshot. Extending the range requires
  a manual full-corpus refresh; monthly current-year invalidation is not a Q2
  freshness guarantee.
- **Q3 source freshness is not automated.** The current-year-only refresh does
  not update historical citation windows or classifications. Q3 is a
  full-corpus analytical snapshot.
- **The Q3 terminal cohorts carry a citation-year settling caveat.** Cells
  whose window ends in 2025 rest on the least-settled citation year in the
  snapshot. The measured discontinuity is indistinguishable from ordinary
  cohort variation, but one snapshot cannot separate settling from genuine
  cohort change, so the terminal point stays a presentation caveat.
- **The dev slice is not bit-exact against prod.** `stg_works` dedups on work
  id after the year filter, so a work OpenAlex re-dated across extraction
  snapshots can land in a dev cohort that prod excludes. Prod is correct; the
  effect is bounded and measured above. Dev remains an analytically faithful
  Q3 preview, not a byte-for-byte one.
- **Year rollover is manual.** Advancing the corpus requires coordinated
  updates to extraction bounds and dbt vars.

## Current work

See `PLAN.md`. Q2's implementation, deployment, prod reconciliation,
analytical inspection, obsolete-relation cleanup, and orchestration validation
are complete; the deployed result awaits project review. Q3's fixed-window
cohort-series replacement, including the secondary pooled comparison, is
implemented, deployed to prod, reconciled under the complete §9d programme,
and documented. Both gold contracts now await project review only. Dashboard
design waits for that review.
