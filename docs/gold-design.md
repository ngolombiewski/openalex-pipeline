# Design: Gold — analytical aggregates (Q1 / Q2 / Q3)

_Scope: the final modeling layer. Reads `silver_works` and produces the small aggregate tables that answer the three analytical questions, each for both ablation variants. This is where the genuinely analytical decisions live — half-life definition, Gini formulation, cohort controls — so several sections end in **flagged decisions** for review before implementation._

_Status: design — discuss the flagged decisions, then hand to an implementing agent._

---

## 0. What gold is

`silver_works` is one classified row per CS work. Gold aggregates it into three question-shaped tables:

| Question | Model | Grain |
| --- | --- | --- |
| Q1 — The Takeover (AI's share over time) | `gold_ai_share_by_year` | publication_year × variant |
| Q2 — The Shelf Life (do AI papers age faster?) | `gold_citation_half_life_by_subfield` | subfield (within a cohort) |
| Q3 — The Winner's Game (is impact more concentrated in AI?) | `gold_citation_gini_by_subfield` | subfield (within a cohort) |

All tables materialize as `table` (tiny outputs, no partitioning). Input is `{{ ref('silver_works') }}` only. No new infra, no Terraform.

---

## 1. Two cross-cutting confounds (read before any question)

Both bite Q2 and Q3, and both come from the data, not from modelling taste:

### 1a. `counts_by_year` is a fixed 2012–2026 window — **verified**

OpenAlex returns per-year citation counts only for a **rolling ~15-year window**, _not_ since publication. Confirmed on the full corpus: across every publication cohort (1985, 1995, 2005, 2015, …), `counts_by_year` starts at **2012** and ends at **2026**.

Consequence for Q2: a paper's early citation years exist in the data **only if the paper was published in 2012 or later**. For pre-2012 papers the first (usually most important) years of the citation curve are missing, so half-life-from-publication is uncomputable for them. Q2 is therefore restricted to a **post-2012 cohort** (§3).

### 1b. Citation counts are age-dependent

`cited_by_count` is cumulative-to-date and `counts_by_year` accrues over a paper's life, so older papers have mechanically more citations. Comparing concentration (Q3) or aging (Q2) **across subfields** is only fair **within a publication cohort** — otherwise a subfield that happens to be older looks more concentrated for purely temporal reasons. Both Q2 and Q3 control for this by fixing a publication-year cohort.

(Q1 is a _ratio_ within each year, so it is immune to both confounds — see §2.)

---

## 2. Q1 — The Takeover: AI share by year

The easy one; no cohort issues. For each `publication_year`, the share of CS works that are AI, for each variant.

- **Denominator:** all `silver_works` in that year (every work is CS by the `field.id:17` extraction filter, 0 null subfields — see silver design). No filtering.
- **Numerator:** `countif(is_ai_strict)` / `countif(is_ai_broad)`.
- **Shape:** long — one row per `(publication_year, variant)` with columns `cs_works`, `ai_works`, `share`. Long keeps the dashboard's strict/broad toggle trivial and matches Q2/Q3's variant handling.

```
gold_ai_share_by_year(publication_year, variant, cs_works, ai_works, share)
```

**Notes / minor decisions:**

- **2026 is partial** (extraction in-flight). The _share_ is still meaningful, but flag the year visiblty as partial in the dashboard.
- Early years (1950s–60s) have tiny `cs_works` and so noisy shares. Keep them (the corpus bounds are deliberate); the dashboard can handle the noise. No minimum-count filter in gold.

---

## 3. Q2 — The Shelf Life: citation half-life by subfield

The hard one. "Do AI papers age faster?" → shorter citation half-life = faster aging.

### 3a. Per-paper half-life definition

For a paper, citation **age** = `citing_year − publication_year`. Order citations by age; the **half-life** is the age at which cumulative citations first reach **50% of the paper's observed total** (median citation age, citation-weighted).

```
cumulative_cites(age) >= 0.5 * total_cites   ->   smallest such age = half_life
```

- **Linear interpolation** between the age just below and at the crossing gives a continuous value (recommended; a paper with citations only at ages 1 and 3 has a half-life between, not snapped to 3). Flag: integer-age (no interpolation) is simpler and probably fine at the median-over-papers level — decision below.
- Drop citation entries with `age < 0` (a small number of records carry pre-publication `counts_by_year` years; they are anomalies, not signal).

### 3b. Cohort restriction (forced by §1a)

Compute half-life **only for papers published 2012–2016**:

- 2012 is the earliest year with full from-publication coverage in the window.
- Through 2026 that cohort has **10–14 years** of follow-up — ample for a median citation age (CS half-lives are typically a few years).
- **Decision (flag):** `2012–2016` (safe: long follow-up) vs a later cut like `2012–2018` (more papers, more "current", but shorter follow-up and more right-censoring of slow-citing papers). Median half-life is robust to the tail, so I lean **2012–2016** but want your call.

### 3c. Zero-citation works

~61% of the corpus has empty `counts_by_year`; within the cohort, papers with **0 observed citations have no half-life** and are excluded. Report the excluded fraction per subfield (an uncited-rate column) so the half-life is read in context — a subfield with a short half-life _and_ high uncited-rate is a different story than one with a short half-life and few uncited papers.

### 3d. Output

```
gold_citation_half_life_by_subfield(
  subfield_id, subfield_display_name,
  is_ai_strict, is_ai_broad,        -- subfield-level labels (1702 in both; 1707 broad only)
  n_papers, n_cited, uncited_rate,
  median_half_life, p25_half_life, p75_half_life
)
```

Grain is **per subfield** (variant-agnostic; the strict/broad labels identify AI
subfields under either definition). They do not make pooled AI-vs-rest metrics
derivable from subfield aggregates; see §9. An intermediate model
`int_paper_half_life` (per-paper, ephemeral or view) does the unnest + cumulative
crossing; the gold model aggregates it to subfield medians.

---

## 4. Q3 — The Winner's Game: citation Gini by subfield

"Is citation impact more concentrated in AI than in other CS subfields?" → Gini of `cited_by_count` per subfield, compared.

### 4a. Gini in SQL

For values `x` sorted ascending with rank `i = 1..n`:

```
gini = sum( (2*i - n - 1) * x ) / ( n * sum(x) )
```

A single window pass: `row_number()` for `i`, `count()` for `n`, `sum()` for the total, per group. `nullif(n * total, 0)` guards an all-zero group.

### 4b. Cohort control (forced by §1b)

`cited_by_count` is age-dependent, so Gini is computed **within a publication cohort**, not over all years pooled. **Decision (flag):** reuse the Q2 cohort (2012–2016) for symmetry and a clean "same papers" story, vs a single recent year, vs a different window. Recommendation: **reuse 2012–2016** — consistent narrative, enough papers per subfield for a stable Gini.

### 4c. Zero-citation works — include

Unlike Q2, Q3 **keeps** zero-citation papers: concentration of impact _is_ the story of the uncited majority vs the cited few, so dropping zeros would understate concentration. (Flag: if you want a "cited-only" Gini as a secondary column, it's cheap to add — but the headline includes zeros.)

### 4d. Output

```
gold_citation_gini_by_subfield(
  subfield_id, subfield_display_name,
  is_ai_strict, is_ai_broad,
  n_papers, total_citations, gini
)
```

Per subfield, within the cohort. The flags support highlighting AI subfields,
not pooling subfield Ginis into an AI-vs-rest Gini; see §9.

---

## 5. Models, materialization, tests

- `models/gold/` — `+materialized: table` block in `dbt_project.yml`.
- Models: `gold_ai_share_by_year`, `int_paper_half_life` (ephemeral/view), `gold_citation_half_life_by_subfield`, `gold_citation_gini_by_subfield`.
- Cohort bounds as **vars** (`half_life_cohort_min: 2012`, `half_life_cohort_max: 2016`) — pinned, reviewable, reused by Q2 and Q3, same pattern as the `subfield_*` vars.
- **Tests (`dbt_utils.accepted_range` is the main guard):**
  - `share` ∈ [0, 1]; `gini` ∈ [0, 1]; `median_half_life` > 0; `uncited_rate` ∈ [0, 1].
  - Q1: `not_null` on `publication_year`, `variant`; one row per `(publication_year, variant)` (`unique_combination_of_columns`).
  - Q2/Q3: `subfield_id` unique per table; `n_papers` > 0.
  - Sanity singular tests: Q1 strict-share ≤ broad-share for every year (the ablation subset relation must survive aggregation); the AI subfield (1702) appears in every gold table.

---

## 6. Decisions to settle before implementing (the flagged ones, gathered)

1. **Q2 cohort** — `2012–2016` (recommended) vs `2012–2018`. §3b.
2. **Q2 interpolation** — linear (recommended) vs integer-age. §3a.
3. **Q3 cohort** — reuse `2012–2016` (recommended) vs another window. §4b.
4. **Q3 zero-citation works** — include in headline Gini (recommended); optional secondary cited-only Gini. §4c.
5. **Q1 partial-2026** — flag column vs documentation-only. §2.

None of these block the _scaffold_ (models, vars, tests); they pin the _numbers_. Recommend resolving 1–4 (the methodology) at review; 5 is cosmetic.

---

## 7. Implementation order

1. `dbt_project.yml`: `gold:` block + cohort vars.
2. `gold_ai_share_by_year` (§2) + tests — cheap, no cohort, validates the variant-share plumbing. Spot-check against the silver anchor (strict ~27.5% overall, but now resolved over time).
3. `int_paper_half_life` (§3a–c) on the cohort, then `gold_citation_half_life_by_subfield` (§3d) + tests. Dev slice first; note the dev decade (1991–2000) is **outside** the half-life cohort, so iterate Q2/Q3 with `--vars '{year_min: 2012, year_max: 2016}'` instead.
4. `gold_citation_gini_by_subfield` (§4) + tests.
5. Prod build; eyeball the headline comparisons (AI vs rest half-life; AI vs rest Gini) for both variants — sign and rough magnitude, not precision.

**Dev-slice caveat (important):** Q2/Q3 are only meaningful on the 2012–2016 cohort, so the usual `1991–2000` dev slice produces empty/garbage half-life and age-confounded Gini. Iterate gold on `--vars '{year_min: 2012, year_max: 2016}'`.

---

## 8. What "done" looks like

- Three gold tables build on dev (2012–2016 slice) then prod; all §5 tests green.
- Q1 reports annual share and `ai_strict ≤ ai_broad` every year; no monotonic
  trend is assumed.
- Q2 returns a per-subfield median half-life over the cohort, with uncited-rate context; AI subfields are directly comparable to other CS subfields.
- Q3 returns a per-subfield Gini ∈ [0,1]; AI subfields are directly comparable
  to other CS subfields. Pooled AI-vs-rest requires paper-level aggregation (§9).
- A reviewer can see that the `counts_by_year` window (§1a) and the age confound (§1b) were handled deliberately, not missed.

---

## 9. Known gap (review finding, 2026-07-09)

**Pooled AI-vs-rest is *not* derivable from the published gold tables.** Earlier
drafts of §3d, §4d, and §8 claimed pooling was a downstream group-by on the
flags. That is only true from *paper-level* rows (`silver_works` /
`int_paper_half_life`). The gold tables publish subfield-grain medians,
percentiles, and Ginis, and none of those compose: you cannot aggregate
subfield medians into a pooled median, nor subfield Ginis into a pooled Gini.
(The STATE.md sanity checks worked around this with unweighted averages of
subfield medians — illustrative, not a real pooled statistic.)

Resolution deferred to the planned Q2/Q3 revisit (cohort coverage, Gini
through the current year). Options there: add variant-grain gold tables
(pooled strict/broad/rest computed from paper level), or pin the dashboard
story as subfield-comparison-only. Until then, the dashboard must not present
pooled AI-vs-rest numbers computed from these tables.
