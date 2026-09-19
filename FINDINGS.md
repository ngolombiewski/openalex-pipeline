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

<!-- prettier-ignore -->
| Bound             | Value                                                                        | Source            |
| ----------------- | ---------------------------------------------------------------------------- | ----------------- |
| Prod run date     | 2026-07-31                                                                   | —                 |
| Corpus            | `year_min` 1950, `year_max` 2026                                             | `dbt_project.yml` |
| Partial year flag | `partial_year` 2026                                                          | `dbt_project.yml` |
| Q2 citation years | `citation_age_year_min` 2012, `citation_age_year_max` 2025                   | `dbt_project.yml` |
| Q3 cohorts        | `gini_cohort_min` 2012, `gini_citation_year_max` 2025 (⇒ latest cohort 2024) | `dbt_project.yml` |
| Dev slice         | publication years 2012–2016                                                  | `--vars` override |
| Extraction filter | `primary_topic.field.id:17`                                                  | `OPENALEX_FILTER` |

The three year-bound families advance **independently**, by explicit changes.
Advancing Q2 or Q3 requires a manual full-corpus refresh plus reconciliation;
advancing the corpus bounds alone does not extend either citation snapshot.

**Read-only audit, 2026-09-19.** All four production gold relations were read
under these unchanged bounds. The Q1 committed extract agrees to its six-decimal
precision; the Q3 committed 2020/five-year measures agree with gold. The audit
rechecked gold-derived summaries, ranks, triangle sizes, cross-grain paper and
citation totals, and the Gini decomposition. No warehouse build was run.
Source-level reconciliation, exclusion counts, including-age-0 Gini sensitivity,
dev/prod deltas, and historical build costs remain measurements from the original
validation; they cannot all be reconstructed from the four gold relations.

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
| pytest | 255 passed |
| Ruff check | passes |
| Ruff format check | passes |
| Pyright | passes |
| dbt manifest | 6 models, 116 data tests, 3 unit tests |
| dbt suite, both targets | 119 checks total: 118 pass, 1 expected warning |
| Expected warning: `warn_citation_age_negative_entries` | 198,882 prod rows / 46,357 dev rows |
| Last full prod staging build | 43.2 GiB billed (cap: 100 GiB/job) |

Prod query cost, maxima observed: `gold_citation_gini_by_subfield` and
`gold_citation_gini_by_group` at 1,072,844,491 bytes processed each; the whole
61-job Q3 build-and-test run processed 4.39 GB. Q2's heaviest job
(`gold_citation_age_by_year`) processed 1,547,972,704 bytes. Everything sits far
below the per-job cap.

---

## Q1 — AI's share of CS works

**Result: both AI definitions reach their highest share in the loaded
1950–2026 series in partial 2026.** Strict AI rises from a **22.5% trough in
2015** to **35.0% in 2025** and **39.8% in partial 2026**; its 1980 share was
30.8%. Broad AI reaches **49.7% in 2025** and **54.7% in partial 2026**, after a
34.5% trough in 2011.

The complete-year distinction matters: broad AI's 2025 share is also a record
over 1950–2025, but strict AI's 2025 share remains below its **35.3% in 1951**.
The strict complete-year record claim is therefore supported only over the
default 1980-onward presentation range, not the full history. This descriptive
series does not establish a causal explanation for the decline and recovery.

**Caveat that must travel with this result:** OpenAlex assigns topics
retroactively using a modern taxonomy. That is what makes a 1980 "AI share"
well-defined at all, and it means the series measures _how today's taxonomy sees
1980_, not how 1980 saw itself.

2026 is flagged `is_partial_year` and must be visually distinguished by any
consumer.

---

## Q2 — Citation-weighted age of cited works

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

## Q3 — Citation concentration (Gini/top-k)

**Result: citation impact in AI is a winner's game, and more so than the
headline Gini shows.**

2020 cohort, five complete calendar years after publication:

<!-- prettier-ignore -->
| Subfield | Share with no ages-1–5 citations | Gini (all) | Gini (cited only) |
|---|---:|---:|---:|
| **Artificial Intelligence** | 0.464 | 0.871 | **0.760** |
| Computer Graphics & CAD | 0.675 | 0.922 | 0.759 |
| **Computer Vision & PR** | 0.353 | 0.839 | **0.751** |
| Information Systems | 0.624 | 0.898 | 0.729 |
| Software | 0.610 | 0.864 | 0.651 |
| Hardware & Architecture | 0.473 | 0.810 | 0.639 |

The all-paper Gini combines two effects: the share of papers receiving no
citations in the selected window and inequality among those receiving citations.
Here "uncited" always means no citations at ages 1–5; publication-year citations
are excluded, so it does not mean never cited.

For this 2020/five-year cell, AI has the highest cited-only Gini of the 11 CS
subfields and CV/PR the third. Their uncited shares are the fourth-lowest and
lowest respectively. Computer Graphics has a near-identical cited-only Gini to
AI, but its uncited share is **1.46 times AI's**, a **21.1 percentage-point**
gap. It has the highest all-paper Gini (**0.922**), followed by Information
Systems (**0.898**); AI ranks fourth (**0.871**). Both the zero share and
cited-only inequality contribute to these all-paper values.

**Hardening over time.** Across cohorts 2012 → 2020 at the same five-year
window, AI's cited-only Gini rises **0.684 → 0.760** while its uncited rate
falls **0.576 → 0.464**.

**The result that must not be overstated.** On the _pooled_ AI-versus-rest view,
AI's **all-paper** Gini is lower than pooled rest of CS in all 11 observable
cohorts at window 3 and five of nine at window 5. The four positive window-5
gaps are small (0.0008–0.0056), so there is no consistent AI excess.

At these two windows, AI's all-paper Gini ranks **3rd–5th of 11** across the
observable cohorts (2012–2022 at window 3; 2012–2020 at window 5), sitting
0.40–0.76 into the min–max spread. Information Systems holds the maximum through
2019; Computer Graphics holds it from 2020 at both windows. These rankings do
not describe cited-only Gini or assert a result over every published window.
Pooled `rest_cs` Gini exceeds the unweighted mean Gini of its constituent
subfields at both windows. Pooling heterogeneous distributions changes the
comparison; the pooled Gini is not an average of subfield Ginis.

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
5 (range −0.0107 to −0.0015); top-k shares move by at most 0.017. AI's all-paper
Gini holds rank 3–5 of 11 under both age-0 variants with two one-position swaps
across 20 cohort/window cases; the pooled comparison shows zero sign reversals.

**Age-0 diagnostics** are group-differentiated but small. Mean
`age0_citation_share` at windows 3 / 5: 8.1% / 4.7% (`ai`), 5.9% / 3.4%
(`cv_pr`), 7.9% / 4.8% (`rest_cs`). The mean reduction in `zero_share` when age 0
is included is 1.7–2.0 **percentage points** at window 3 and 1.2–1.4 percentage
points at window 5. These are unweighted means over each group's observable
cohorts at the stated window.

**Negative-age entries inside the Q3 cohort range**: 192,150 entries carrying
717,886 citation events, ages −12 to −1, ~1.1% of the cohorts' recorded event
weight. The ages-1..N window excludes them.

**Terminal-edge diagnostic — did not trigger retreat to 2024.** At window 3 the
terminal 2022 cohort moves −0.013 / −0.010 / −0.006 in pooled all-paper Gini
against 2021 (AI / CV-PR / rest-CS); at window 5 the terminal 2020 cohort moves
−0.005 / −0.004 / **+0.003**
against 2019 in the same group order. Zero shares fall in all six comparisons.
Citations per paper rise in five; **AI at window 5 falls by 0.197**. The
pattern does not show a uniform loss of citation coverage, but one snapshot
cannot rule out settling. Across subfields on the whole 2025-ending diagonal,
all-paper Gini cohort steps have a similar scale to interior steps (mean
−0.0018, sample sd 0.0156 vs −0.0012, sample sd 0.0120).

**Largest cohort steps occur in small subfields at short windows.** Software's
2023 cohort, at 4,859 papers, moves +0.079 in all-paper Gini against 2022 at age
2. Over the same cohort transitions (2012→2013 through 2019→2020), mean absolute
subfield steps are 0.00761 at window 5 versus 0.00771 at window 3. This modest
average difference does not establish that every window-5 series is smoother.

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
