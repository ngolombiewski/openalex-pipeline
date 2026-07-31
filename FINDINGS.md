# FINDINGS.md

Current analytical results and reconciliation baselines, at agent granularity.

**Purpose.** Two things: the analytical output of the pipeline, and the numbers
against which a future run can be checked for drift. Rewritten after each prod
run that changes results.

**Reading rule.** Every number here is meaningless without its bounds. The
snapshot block below stamps the configuration all results were computed under. A
number that differs from this file is only a regression if the bounds match; if
the bounds advanced, the number is _expected_ to move and this file is stale.

**Related.** `README.md` narrates a subset of this for human readers and is not
authoritative. Rationale for why measures are defined this way is in
`DECISIONS.md`. Structure is in `OVERVIEW.md`.

---

## Snapshot bounds

_All results below were computed under this configuration._

| Bound             | Value                                                                        | Source            |
| ----------------- | ---------------------------------------------------------------------------- | ----------------- |
| Prod run date     | 2026-07-31                                                                   | —                 |
| Corpus            | `year_min` 1950, `year_max` 2026                                             | `dbt_project.yml` |
| Partial year flag | `partial_year` 2026                                                          | `dbt_project.yml` |
| Q2 citation years | `citation_age_year_min` 2012, `citation_age_year_max` 2025                   | `dbt_project.yml` |
| Q3 cohorts        | `gini_cohort_min` 2012, `gini_citation_year_max` 2025 (⇒ latest cohort 2024) | `dbt_project.yml` |
| Dev slice         | publication years 2012–2016                                                  | `--vars` override |
| Extraction filter | `primary_topic.field.id:17`                                                  | `OPENALEX_FILTER` |

The three year-bound families advance **independently** and only after a manual
full-corpus refresh plus reconciliation. Changing one does not license changing
another.

---

## Corpus reconciliation

_The primary drift baseline. A mismatch here invalidates everything below._

<!-- prettier-ignore -->
| Quantity | Value |
|---|---:|
| Publication-year shards (1950–2026, 2026 partial) | 77 |
| Bronze manifest — extracted rows | 14,775,131 |
| Prod `stg_works` / `silver_works` rows | 14,723,333 |
| Difference (retraction/paratext/null-status/dedup) | 51,798 |
| — of which NULL `is_retracted`, conservatively dropped | 1,282 |
| Dev slice `stg_works` rows (2012–2016) | 2,668,938 |
| Prod rows in the same range | 2,668,926 |

The dev/prod delta of 12 works is expected and explained in `DECISIONS.md` §11.

**Classification sanity anchors** — not targets, and not stable across
retroactive OpenAlex reclassification:

- `ai_strict` ≈ 27.5% of CS works
- `ai_broad` ≈ 40.0% of CS works

---

## Build and test baselines

<!-- prettier-ignore -->
| Check | Baseline |
|---|---|
| pytest | 247 passed |
| Ruff check | passes |
| Ruff **format** check | 19 pre-existing files flagged, not applied — outside recent changes |
| dbt manifest | 6 models, 110 data tests, 3 unit tests |
| dbt suite, both targets | 112 checks, 1 expected warning |
| Expected warning: `warn_citation_age_negative_entries` | 198,882 prod rows / 46,357 dev rows |
| Last full prod staging build | 43.2 GiB billed (cap: 100 GiB/job) |

Prod query cost, maxima observed: `gold_citation_gini_by_subfield` and
`gold_citation_gini_by_group` at 1,072,844,491 bytes processed each; the whole
61-job Q3 build-and-test run processed 4.39 GB. Q2's heaviest job
(`gold_citation_age_by_year`) processed 1,547,972,704 bytes. Everything sits far
below the per-job cap.

---

## Q1 — The Takeover

**Result: AI's share of CS output is at an all-time high, but the path is not
monotone.** ≈31% in 1980, a trough near 23% around 2012, ≈35% in 2025, ≈40% in
the partial 2026 data. The dip-and-surge shape is consistent with the
qualitative "AI winters" narrative.

**Caveat that must travel with this result:** OpenAlex assigns topics
retroactively using a modern taxonomy. That is what makes a 1980 "AI share"
well-defined at all, and it means the series measures _how today's taxonomy sees
1980_, not how 1980 saw itself.

2026 is flagged `is_partial_year` and must be visually distinguished by any
consumer.

---

## Q2 — The Shelf Life

**Result: citation attention has shifted toward younger work across all of CS,
with CV/PR generally the most recent.**

Median citation age, 2012 → 2025:

<!-- prettier-ignore -->
| Group | 2012 | 2025 | Reaches 5 |
|---|---:|---:|---|
| `ai` | 8 | 5 | 2023 |
| `cv_pr` | 7 | 5 | 2018 |
| `rest_cs` | 7 | 5 | 2022 |

Share of 2025 citation events going to works aged ≤ 5 years: **55.4%** (`ai`),
**57.2%** (`cv_pr`), **54.3%** (`rest_cs`).

**Structural baselines.** Prod Q2 contains exactly **42 rows** — three groups ×
citation years 2012–2025, with no 2026 row. Citation-event and distinct-work
totals reconcile exactly to an independent eligible-silver aggregation for every
year; every recorded delta is zero. A nonzero delta is a hard regression.

**Diagnosed anomaly, excluded by contract.** Prod validation excluded
**198,882** positive negative-age entries carrying **779,220** citation events
(~0.70% of eligible-plus-excluded event weight). These are works with citation
years before their publication year. They decline from 25,065 entries in 2012 to
818 in 2025; ages span −14 to −1. This is the source of the expected dbt
warning.

**Framing constraints.** These are citation-weighted ages of _cited works_, not
evidence about what AI-authored papers cite, and not proof of faster intrinsic
obsolescence. Q2 is a snapshot through citation year 2025, not a live metric.

---

## Q3 — The Winner's Game

**Result: citation impact in AI is a winner's game, and more so than the
headline Gini shows.**

2020 cohort, five complete calendar years after publication:

<!-- prettier-ignore -->
| Subfield | Uncited rate | Gini (all) | Gini (cited only) |
|---|---:|---:|---:|
| **Artificial Intelligence** | 0.46 | 0.871 | **0.760** |
| Computer Graphics & CAD | 0.68 | 0.922 | 0.759 |
| **Computer Vision & PR** | 0.35 | 0.839 | **0.751** |
| Information Systems | 0.62 | 0.898 | 0.729 |
| Software | 0.61 | 0.864 | 0.651 |
| Hardware & Architecture | 0.47 | 0.810 | 0.639 |

The all-papers Gini conflates two effects: how many papers are never cited, and
how unequal the cited ones are. Decomposing reorders the field. AI has the
highest cited-only Gini in CS and CV/PR the third — but what distinguishes them
is the _pairing_: both combine that concentration with among the lowest uncited
rates. AI papers get cited more often than average, and the winnings still pool
at the top. The contrast is Computer Graphics, whose near-identical cited-only
Gini comes with more than twice the uncited rate, and Information Systems, which
tops the all-papers Gini purely because 62% of its papers are never cited.

**Hardening over time.** Across cohorts 2012 → 2020 at the same five-year
window, AI's cited-only Gini rises **0.684 → 0.760** while its uncited rate
falls **0.576 → 0.464**.

**The result that must not be overstated.** On the _pooled_ AI-versus-rest view,
AI is **not** more concentrated overall — the all-papers Gini gap runs slightly
the other way for most cohorts. AI is never the most concentrated CS subfield:
it ranks **3rd–5th of 11** in every cohort at both windows, sitting 0.40–0.76
into the min–max spread. Information Systems holds the maximum throughout.
Pooled `rest_cs` Gini exceeds the mean individual-subfield Gini because pooling
heterogeneous subfields adds between-subfield inequality — a structural
asymmetry, now measured.

**Structural baselines.**

<!-- prettier-ignore -->
| Quantity | Prod | Dev (2012–2016) |
|---|---:|---:|
| Cohort/age cells | 91 | — |
| `gold_citation_gini_by_subfield` rows | 1,001 | 605 |
| `gold_citation_gini_by_group` rows | 273 | 165 |

Prod publishes the complete observable triangle `[2012, 2024] × [1, 2025−y]`. No
interior cell absent, nothing beyond the configured edge at either grain.

**Reconciliation baselines** (all must stay at zero):

- Cross-grain sum mismatches across all 91 cells: **0**
- Violations of `G = p + (1−p)·G_cond` across every published row: **0**
- Disagreement with independent per-cell source oracles: **0**
- Display-label conflicts / fallbacks in dev and prod silver: **0**
- `__unclassified__` bucket occupancy: **empty** (defensive only)

Dev/prod overlap reconciles **under tolerance, not exactly**: all 605 keys match
with zero classification-flag deltas, but 96 cells carry nonzero integer deltas
and ratios differ by up to 2.7e-5. Fully accounted for by the 12-work
slice-boundary dedup difference (`DECISIONS.md` §11).

**Age-0 sensitivity — substantively neutral, measured not assumed.** Including
age 0 moves subfield Gini by a mean of −0.0055 at window 3 and −0.0042 at window
5 (range −0.0107 to −0.0015); top-k shares move by at most 0.017. AI holds rank
3–5 of 11 under both variants with two one-position swaps across 20
cohort/window cases; the pooled comparison shows zero sign reversals.

**Age-0 diagnostics** are group-differentiated but small. Mean
`age0_citation_share` at windows 3 / 5: 8.1% / 4.7% (`ai`), 5.9% / 3.4%
(`cv_pr`), 7.9% / 4.8% (`rest_cs`). Mean `zero_share` gap is 1.7–2.0% at window
3 and 1.2–1.4% at window 5.

**Negative-age entries inside the Q3 cohort range**: 192,150 entries carrying
717,886 citation events, ages −12 to −1, ~1.1% of the cohorts' recorded event
weight. The ages-1..N window excludes them.

**Terminal-edge diagnostic — did not trigger retreat to 2024.** At window 3 the
terminal 2022 cohort moves −0.013 / −0.010 / −0.006 in Gini against 2021; at
window 5 the terminal 2020 cohort moves −0.005 / −0.004 / **+0.003**
against 2019. The direction contradicts under-indexing: terminal cohorts show
_higher_ citations per paper and _lower_ zero shares. Across the whole
2025-ending diagonal, cohort steps are indistinguishable from the interior (mean
−0.0018, sd 0.0156 vs −0.0012, sd 0.0120).

**No structural discontinuity in the cohort series.** Largest steps sit in the
smallest subfields at the shortest windows — Software at 4,859 papers moves
+0.079 at age 2. Window-5 series are smoother than window-3 throughout.

---

## Presentation constraints

_Binding on any consumer of gold, including the planned dashboard._

- **Visibly distinguish the partial current publication year** (2026) in Q1.
- **Label Q2 as a snapshot** through citation year 2025, not a live metric.
- **Never describe Q3 subfield comparisons as pooled AI-vs-rest results.** They
  are two relations at different grains, not one filterable table.
- **Caveat `rest_cs` pooling** wherever the pooled relation appears — it carries
  between-subfield inequality that no individual subfield does.
- **Caveat age-0 exclusion, incomplete windows, citation-year settling, and
  truncated heatmap cells** in Q3 views.
- **Caveat retroactive taxonomy assignment** wherever Q1's historical series
  appears.

---

## Known limitations

- **Dashboard not implemented.** Streamlit is the remaining application layer.
- **Q2 and Q3 freshness is not automated.** The monthly current-year refresh
  does not update historical citation windows or classifications. Both are
  full-corpus analytical snapshots; extending their ranges is a manual
  operation.
- **Year rollover is manual.** Advancing the corpus needs coordinated changes to
  extraction bounds and dbt vars.
- **Q3's earliest cohorts may become unrebuildable.** `counts_by_year` is a
  rolling window; a future full-corpus re-extraction may drop citation years
  2012–13. No mitigation in place.
- **The terminal cohort carries a settling caveat** that one snapshot cannot
  resolve — see the diagnostic above.
