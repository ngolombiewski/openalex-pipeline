# Gold Q3 revisit design — citation concentration

*Status: approved for implementation; implemented and validated in dev on
2026-07-31. Prod deployment, reconciliation, analytical validation, and final
review remain pending. The deployed prod Q3 remains the cumulative-count
subfield Gini described in `docs/design-archive/gold-design.md` until those
steps complete.*

## 1. Decision

Q3, **The Winner's Game**, asks:

> Is citation impact more concentrated in Artificial Intelligence than in
> other Computer Science subfields — and how has that concentration changed
> across publication cohorts?

The revision makes four changes to the deployed Q3:

1. **Fixed citation window replaces cumulative counts.** A paper's impact is
   measured by citations received in a fixed number of complete calendar years
   following its publication year, reconstructed from `counts_by_year`, rather
   than by cumulative `cited_by_count` as of the snapshot.
2. **A publication-year axis is added.** Q3 becomes a cohort series rather
   than a single 2012–2016 snapshot, so concentration trends are visible.
3. **The subfield grain remains the primary comparison**, rebuilt on the new
   window metric so AI's position among individual CS subfields is measured
   like for like.
4. **The measure set expands** from two Ginis to a three-part decomposition
   (§5a), tail shares, and two age-0 diagnostics.

A pooled `ai` / `cv_pr` / `rest_cs` relation is added as a secondary lens,
mirroring Q2's exclusive partition and computed directly over the pooled paper
population. It answers a different question from the primary subfield view:
AI versus the heterogeneous union of the rest of CS, not AI versus a typical
other subfield. Nothing in the deployed subfield relation is removed; its
grain and measures change as specified below.

### 1a. Why a fixed window

`cited_by_count` is cumulative to the snapshot date, so it is a function of a
paper's age. Comparing cohorts on it measures elapsed time, not impact. The
deployed Q3 controls for this by freezing a single 2012–2016 cohort, which
buys comparability at the cost of having no time axis at all — Q3 is the only
one of the three questions that cannot show a trend.

A fixed post-publication calendar window gives every paper the same number of
complete calendar years of exposure. This removes the dominant mechanical age
confound and permits the publication-year axis. It also stops mechanical
citation accrual after the window endpoint; retrospective source corrections
and classification changes can still revise a closed window (§10).

“Complete calendar year” does not mean “equally mature in OpenAlex.” At any
fixed window, the newest eligible cohort ends in the latest configured
citation year, which has had the least time for retrospective citation
indexing to settle. Missing late-indexed citations can raise `zero_share` if
they would have reached currently uncited papers, but the direction of the
Gini effect is not determined: it depends on which papers' citations are
missing. The terminal cohort point is therefore exposed to a
**citation-year-settling edge effect** even though every paper has the same
calendar exposure. §9d sizes the observable discontinuity, §10 records the
snapshot timing, and §11b makes the limitation a presentation caveat.

### 1b. Why the window excludes the publication year

The window is **ages 1 through N**, not 0 through N.

Age 0 is a partial year whose length is set by publication month: a January
paper has roughly twelve months of age-0 exposure, a December paper roughly
none. Including it yields a window of variable length — about 3 to 4 years for
a nominal 3-year window — with the variation driven by publication date rather
than impact. Ages 1..N is exactly N complete calendar years following the
publication year.

This is not literally the paper's first N years of life. The calendar window
starts roughly 0–12 months after publication depending on publication month,
so papers receive equal-duration windows at different lifecycle offsets. That
is the most precise comparison the annual source supports.

Sub-year windowing is not an alternative. `counts_by_year` is annual and
carries no within-year resolution, so citations cannot be attributed to months
even though `publication_date` is known.

The exclusion is not assumed to be group-neutral. §5c specifies explanatory
diagnostics, and §9d specifies the direct sensitivity analysis that determines
whether including age 0 would change the substantive result.

## 2. Meaning and orientation

The unit of observation is a **paper in a publication cohort**. Every paper
enters once; its outcome is the citations received inside its window.
Classification applies to the paper itself. This is the citing-side-agnostic
view: the source does not identify citing works, so Q3 neither restricts nor
groups them.

For a paper `p` and citation age `a`:

```text
window_citations(p, a) = sum over k in 1..a of
                         p.counts_by_year[p.publication_year + k].cited_by_count
```

Concentration measures are computed over the distribution of
`window_citations` across all papers in a cohort cell, **including papers with
zero**. The uncited majority against the cited few is the concentration story;
dropping zeros would understate it and is published separately instead.

This answers:

> Among CS papers published in year `y`, how unequally were citations received
> during the first `a` complete calendar years following the publication year
> distributed?

It does **not** answer:

> Are individual AI papers more highly cited than non-AI papers?

That is a level question, not a concentration question. A group can have
higher mean citations and lower inequality simultaneously. Q1 provides volume
context; Q3 describes distribution shape only.

## 3. Population and time bounds

### 3a. Paper population

The population is every row in `silver_works` whose `publication_year` falls in
the Q3 cohort range `[gini_cohort_min, gini_citation_year_max - 1]`. That is
the model's filter — not the `year_min` / `year_max` corpus bounds, which are
independent of it by design (§8). Because `silver_works` itself carries only
the corpus slice, the population actually built is the intersection of the two
ranges, which is why §9b's coverage expectations are intersected rather than
absolute. Trust the silver contract: gold does not re-validate work ids, corpus
membership, or classification.

A paper with no `counts_by_year` entries in its window is a **zero-citation
paper**, not a missing row. It counts in `n_papers` and contributes a zero to
every concentration measure. This is the single most important population
rule in this design: silently dropping such papers would convert the headline
measure from concentration into inequality-among-the-noticed.

### 3b. The `counts_by_year` window is a hard constraint

As verified in `docs/design-archive/gold-design.md` §1a, OpenAlex returns
`counts_by_year` over a **rolling ~15-year window**, currently 2012–2026, for
every publication cohort regardless of publication year. A paper's early
citation years therefore exist in the data only if those years fall inside
that window.

This bounds the cohort floor. Age 1 for publication year `y` is citation year
`y + 1`, and the age-0 diagnostic in §5c requires citation year `y` itself.
Both must be ≥ 2012, so:

```text
gini_cohort_min: 2012
```

Publication year 2011 is technically observable at ages ≥ 1 but has no
observable age 0, which would null the diagnostics exactly where they are
needed. It is excluded.

Pre-2012 cohorts must never be admitted by relaxing this bound. Their window
citations would evaluate to zero rather than null, which would not fail a test
— it would silently fabricate a `zero_share` of 1.0 and undefined
concentration measures. §7 specifies the guard.

### 3c. The observable triangle

The upper citation-year bound is the latest complete year in the current
snapshot:

```text
gini_citation_year_max: 2025
```

Partial 2026 data is excluded. The maximum observable age for cohort `y` is
therefore `gini_citation_year_max - y`, and the published grain is a triangle:

```text
publication_year y in [2012, 2024]
citation_age     a in [1, 2025 - y]
```

Cohort 2012 reaches age 13; cohort 2024 exists only at age 1. **All observable
cells are published** — the full lifecycle is analytically interesting and the
row count is trivial.

Those literal cohort bounds are the prod triangle at the current vars. Under a
dev slice the built cohorts are their intersection with `year_min` /
`year_max` (§3a, §8); the age range of each built cohort is unaffected, because
`stg_works` carries every selected paper's complete `counts_by_year`.

`gini_cohort_max` is **removed as a var**. The latest usable cohort is a
derived consequence of `gini_citation_year_max` (2024, the last year with at
least age 1 observable), not an independent analytical choice. Pinning both
would create a pair that can drift into inconsistency; deriving it cannot.

Cells beyond the triangle are **absent rows**, never null rows. "Not yet
observable" and "mathematically undefined" must remain distinguishable in the
output. See §7b.

### 3d. Primary window and ablation

The primary window is **ages 1–3**; **ages 1–5** is the ablation. Neither
appears in the schema: `citation_age` is the window, so both are slices of the
published table and the choice is a presentation concern only.

At `gini_citation_year_max: 2025` the latest eligible cohort is **2022** at
age 3 and **2020** at age 5. Later cohorts have no row at those selected
windows; views must not substitute their shorter observed windows.

## 4. Grains and groups

Two table-materialized models publish **identical measure columns** at
different grains:

| Model | Grain |
|---|---|
| `gold_citation_gini_by_subfield` | `subfield_id` × `publication_year` × `citation_age` |
| `gold_citation_gini_by_group` | `cited_group` × `publication_year` × `citation_age` |

The subfield model is the primary analytical output. The group model is an
additional pooled comparison and must not replace the subfield view in
interpretation or presentation.

The group partition is exactly Q2's, reusing the same pinned subfield id vars:

| `cited_group` | Rule |
|---|---|
| `ai` | `primary_topic_subfield_id = subfield_ai` (`1702`) |
| `cv_pr` | `primary_topic_subfield_id = subfield_cv_pr` (`1707`) |
| `rest_cs` | Every other `silver_works` row |

The `rest_cs` fallback preserves the complete silver denominator, including
rows with a null subfield id, consistent with
[Q2 §4](gold-q2-revisit-design.md#4-cited-work-groups).

The column keeps Q2's `cited_group` name for cross-question symmetry, but the
name is looser here: Q3 has no citing side, and an uncited paper still carries
a `cited_group`. The column classifies the paper by its own subfield, not by
any citation relationship, and the model docstring must say so.

The subfield model preserves the same denominator through one explicit
synthetic reconciliation bucket:

| Source rule | `subfield_id` | `subfield_display_name` |
|---|---|---|
| `primary_topic_subfield_id is null` | `__unclassified__` | `Unclassified` |

The sentinel is a fixed model contract, not a dbt var. OpenAlex subfield ids
are URLs, so it cannot collide with a real id. The bucket participates in
model and cross-grain reconciliation but is not a CS subfield and is excluded
from AI's analytical rank or position among real subfields. If silver contains
no null-subfield papers for a publication cohort, no sentinel row is emitted.

### 4a. Why the pooled grain must be computed directly

The Gini coefficient does not aggregate. There is no weighted combination of
subfield Ginis that yields the Gini of their union, because the union
introduces between-subfield differences in citation level that within-subfield
statistics cannot express. A pooled `rest_cs` figure therefore exists only if
computed over the pooled population, which is why it is added at source rather
than derived downstream.

The same non-aggregability is why the publication-year axis is part of the
grain rather than something a consumer can collapse. Ginis do not pool across
cohorts either.

### 4b. Why the subfield grain is primary

`ai` and `cv_pr` are each a single subfield; `rest_cs` pools many. Only
`rest_cs` therefore carries between-subfield citation-level variation that is
absent from either single-subfield group. This can raise pooled concentration,
but its direction relative to any individual constituent is not guaranteed.
The comparison is structurally asymmetric either way.

The subfield relation directly answers the project's stated question by
showing where AI's concentration falls within the spread of individual
subfield values. It serves this role **only because it is rebuilt on the same
window metric** — compared against cumulative-count subfield figures it would
be a different statistic rather than a like-for-like comparison.

No strict/broad variant grain is published at either grain. Under an exclusive
partition the group *is* the classification, and a merged AI+CV/PR
concentration figure would describe a third population whose value says
nothing about either constituent. The subfield model retains `is_ai_strict`
and `is_ai_broad` as row labels, matching the deployed contract; they do not
create variant-grain aggregates. The silver flags remain unchanged.

## 5. Measures

### 5a. The concentration decomposition

Three of the four headline measures form an **exact identity**, not three
independent signals. For a cohort cell with zero-share `p`, Gini over the full
population `G`, and Gini over cited papers only `G_cond`:

```text
G = p + (1 - p) * G_cond
```

This is exact for finite samples under the estimator used here, not
asymptotic. Sorted ascending with `i = 1..n`:

```text
G = sum((2i - n - 1) * x_i) / (n * sum(x_i))
```

which is algebraically the mean-absolute-difference form
`sum_i sum_j |x_i - x_j| / (2 n^2 mu)`. Splitting that double sum into
zero–zero pairs (contributing nothing), zero–cited pairs, and cited–cited
pairs, then dividing by `2 n^2 mu` with `mu = (1 - p) mu_cited`, yields the
identity. It behaves correctly at the boundaries: `p = 0` gives `G = G_cond`,
`G_cond = 0` gives `G = p`, and `p -> 1` gives `G -> 1`.

The redundancy is the point. `zero_share` and `gini_cited_only` explain
exactly *why* `gini` moved — whether concentration rose because more papers
received nothing, or because attention among noticed papers became more
unequal. §9b turns the identity into a test.

| Measure | Column | Role |
|---|---|---|
| Overall Gini, zeros included | `gini` | Headline: complete allocation of attention |
| Zero-citation share | `zero_share` | Was it broader exclusion? |
| Gini among cited papers | `gini_cited_only` | Or inequality among the noticed? |

### 5b. Tail shares

Top-k shares are **not** determined by the identity and are the genuinely
additional signal: Gini can move without the extreme tail moving, and vice
versa. Three thresholds are published because together they sketch the upper
tail of the Lorenz curve rather than a single point, at no extra cost.

Definition, for `k` in {1%, 5%, 10%}:

> Rank the cohort cell's papers by `window_citations` descending. Take the top
> `ceil(k * n_papers)` papers. The measure is their summed window citations
> divided by the cell's total window citations.

Three properties must be stated in the model docstring:

1. **The population is the full cohort, including zero-citation papers.**
   Taking the top k% of *cited* papers instead would make the measure move
   onto a changing cited-paper denominator and answer a different question.
2. **It is `ceil(k * n)` papers, not exactly k% of them.** For `n = 101`,
   `ceil(0.01 * 101) = 2`, which is ~1.98%. This is a discrete rule and must
   be documented as such. Fractional allocation of the boundary paper is not
   worth the complexity.
3. **The published share is tie-invariant.** Every paper at the cut boundary
   carries an identical citation count, so which tied papers fall inside the
   cut cannot change the summed numerator. The frequency-based computation in
   §7d allocates only the required number of papers from the boundary
   frequency; no paper-level secondary ordering is required.

Column names: `top1_share`, `top5_share`, `top10_share`.

The paper counts are exactly `ceil(k * n_papers)` and are therefore derivable
from a published column. They are not stored.

### 5c. Age-0 diagnostics and sensitivity

Excluding age 0 (§1b) is not assumed to be group-neutral. AI and CV/PR run on a
preprint-and-conference cycle with fast early citation; the rest of CS skews
slower and more journal-shaped. Age-0 citations are therefore plausibly a
larger share of AI's total, and excluding them plausibly trims hardest from
the fast-rising papers that drive concentration.

Two published diagnostics explain the scale of the exclusion:

| Column | Definition | Diagnoses |
|---|---|---|
| `age0_citation_share` | Age-0 citations / citations at ages 0..a | Citation mass discarded by the primary window |
| `zero_share_including_age0` | Papers with zero citations at ages 0..a / all papers | Direct age-0-inclusive comparator for `zero_share` |

Both are age-relative, so they vary across the row's `citation_age` in step
with the measure they qualify.

`age0_citation_share` deliberately uses ages 0..a as its denominator rather
than lifetime citations. A lifetime denominator is cumulative-to-snapshot and
would continue accruing beyond the comparison window. It is null only when
the total citation count over ages 0..a is zero. `zero_share_including_age0`
is always defined for a published cell because `n_papers >= 1`, and
`zero_share - zero_share_including_age0` is the absolute paper-share effect of
excluding age 0.

These diagnostics do **not** determine the effect on `gini`,
`gini_cited_only`, or top-k shares: equal discarded mass can be distributed
very differently across papers. The actual sensitivity analysis therefore
recomputes the complete measure set over ages 0..3 and 0..5 during prod
validation (§9d). The alternate measures are validation evidence, not
published columns. No binary materiality threshold is pinned before seeing
the result; approval records the exact deltas and whether they alter the
substantive comparisons.

## 6. Model contracts

Both models are table-materialized and use enforced dbt contracts:
`config.contract.enforced: true`, with every column's `data_type` pinned in
`_gold.yml`.

Canonical columns for `gold_citation_gini_by_subfield`, in order:

| Column | BigQuery type | Contract |
|---|---|---|
| `publication_year` | `INT64` | `[gini_cohort_min, gini_citation_year_max - 1]` |
| `subfield_id` | `STRING` | Grain key, including the fixed sentinel |
| `subfield_display_name` | `STRING` | Non-null presentation label, not grain; `coalesce` fallback per §6a |
| `is_ai_strict` | `BOOL` | Row label, not grain |
| `is_ai_broad` | `BOOL` | Row label, not grain |
| `citation_age` | `INT64` | `[1, gini_citation_year_max - publication_year]` |
| `n_papers` | `INT64` | Cohort cell size; `>= 1` |
| `total_citations` | `INT64` | Window citations, ages 1..`citation_age`; `>= 0` |
| `zero_share` | `FLOAT64` | `[0, 1]` |
| `gini` | `FLOAT64` | `[0, 1]`, nullable per §7b |
| `gini_cited_only` | `FLOAT64` | `[0, 1]`, nullable per §7b |
| `top1_share` | `FLOAT64` | `[0, 1]`, nullable per §7b |
| `top5_share` | `FLOAT64` | `[0, 1]`, nullable per §7b |
| `top10_share` | `FLOAT64` | `[0, 1]`, nullable per §7b |
| `age0_citation_share` | `FLOAT64` | `[0, 1]`, nullable per §7b |
| `zero_share_including_age0` | `FLOAT64` | `[0, 1]`, non-null |

Canonical columns for `gold_citation_gini_by_group`, in order:

| Column | BigQuery type | Contract |
|---|---|---|
| `publication_year` | `INT64` | `[gini_cohort_min, gini_citation_year_max - 1]` |
| `cited_group` | `STRING` | Grain key; `ai`, `cv_pr`, or `rest_cs` |
| `citation_age` | `INT64` | `[1, gini_citation_year_max - publication_year]` |
| `n_papers` | `INT64` | Cohort cell size; `>= 1` |
| `total_citations` | `INT64` | Window citations, ages 1..`citation_age`; `>= 0` |
| `zero_share` | `FLOAT64` | `[0, 1]` |
| `gini` | `FLOAT64` | `[0, 1]`, nullable per §7b |
| `gini_cited_only` | `FLOAT64` | `[0, 1]`, nullable per §7b |
| `top1_share` | `FLOAT64` | `[0, 1]`, nullable per §7b |
| `top5_share` | `FLOAT64` | `[0, 1]`, nullable per §7b |
| `top10_share` | `FLOAT64` | `[0, 1]`, nullable per §7b |
| `age0_citation_share` | `FLOAT64` | `[0, 1]`, nullable per §7b |
| `zero_share_including_age0` | `FLOAT64` | `[0, 1]`, non-null |

`n_papers` is **constant across `citation_age`** within a grain cell: the
cohort is fixed and papers do not leave it. This is what makes a row
comparable left to right across the lifecycle, and §9b tests it.

For real subfields, the subfield model joins one stable label mapping per
`subfield_id` as specified in §6a. The synthetic bucket uses the fixed id and
display name from §4. The group model needs no display or AI-label columns.

### 6a. Display-name nullability is not assumed

`primary_topic_subfield_display_name` is parsed with `json_value` in
`stg_works` and carries no upstream non-null or single-value guarantee; the
deployed Q3 has no `not_null` test on it. The enforced dbt contract in §6 pins
column presence and type, not value-level nullability: the generic `not_null`
test in §9a runs after materialization. The fallback below is therefore a
presentation contract, not a claim that contract enforcement would itself
reject a null.

Three rules make the column stable and safe to pin:

1. Build one label mapping per real `subfield_id` over the complete **built
   eligible Q3 population**, before cohort-age aggregation. The published
   value is `coalesce(max(display_name), subfield_id)`. `max` is deterministic;
   it is not permission to choose among conflicts.
2. Join that one mapping to every cohort-age row for the subfield. A missing
   label therefore falls back to the id for the whole built series, rather
   than producing a name in one cohort and an id in another.
3. Conflicting labels are a **test failure, not a silent `max` pick**. The §9b
   source-label-consistency test asserts at most one distinct non-null display
   name per real `subfield_id` within the built eligible population. A separate
   output invariant asserts exactly one non-null published display name per
   real `subfield_id`.

Before replacing the prod relation, implementation must report both the
distinct-source-label conflict count and the fallback count over dev and prod
silver populations (§9d). The deterministic mapping keeps the output
reproducible even if the conflict preflight fails; promotion stops on any
conflict.

### 6b. Model decomposition

Prefer one question-shaped SQL model per grain with named CTEs. The two models
require the identical per-paper window expansion and differ only in partition
key, so a shared macro emitting that expansion is explicitly authorized.

Computing the expansion twice is **accepted**, not avoided: Q2's comparable
scan billed 1.5 GiB against a 100 GiB per-job cap, so a second pass is not a
cost argument for an intermediate model. An intermediate model is justified
only if implementation demonstrates a separately testable contract.

## 7. Input handling and edge cases

### 7a. Source rules

For eligible publication cohorts, the Q3 source read range is
`[publication_year, gini_citation_year_max]`: age 0 is required for
diagnostics and sensitivity, while ages 1 and above feed the published
window. Gold unnests `silver_works.counts_by_year` and applies:

1. An entry contributes to the row at `citation_age = a` only when its
   citation year lies in `[publication_year + 1, publication_year + a]`. The
   `gini_citation_year_max` bound caps the read range and the published
   triangle; it is **not** the per-row window bound, which is
   `publication_year + citation_age`. Age-0 entries are read only by the §5c
   diagnostics and §9d sensitivity analysis.
2. Positive counts contribute their full integer weight; zero counts
   contribute nothing.
3. Null citation years are invalid anywhere in an eligible paper's array.
   Within the Q3 source read range, null counts, negative counts, and duplicate
   `work id × citation year` entries are invalid input. The existing shared
   `assert_citation_age_source_valid.sql` test fails loudly on each class. Its
   bounded checks must cover the union of the active Q2 and Q3 citation-year
   ranges:

   ```text
   lower bound = least(citation_age_year_min, gini_cohort_min)
   upper bound = greatest(citation_age_year_max, gini_citation_year_max)
   ```

   Null years remain invalid anywhere in the array, independent of those
   bounds.
4. Entries whose citation year precedes publication year have negative age
   and are excluded from both the window and the diagnostics. Q2 already
   measures this anomaly class at roughly 0.70% of event weight. The existing
   shared `warn_citation_age_negative_entries.sql` retains warn severity and
   uses the same union bounds as rule 3. Q3 does not add a duplicate permanent
   warning test; §9d runs a bounded validation query to record the count and
   event weight for the eligible Q3 population specifically.
5. Papers absent from `counts_by_year` entirely, or absent within the window,
   are zero-citation papers per §3a — never dropped.

### 7b. Undefined versus unobservable

| Situation | Output |
|---|---|
| `citation_age > gini_citation_year_max - publication_year` | **Row absent** |
| `total_citations = 0` | `gini`, `gini_cited_only`, and all top-k shares are **NULL**; `zero_share` is `1.0` |
| Citations at ages 0..`citation_age` total zero | `age0_citation_share` **NULL** |
| `total_citations = 0` but age-0 citations are positive | `age0_citation_share` is `1.0` |
| No cited papers in cell | `gini_cited_only` **NULL** |
| `n_papers = 0` | **Row absent** — an empty cohort cell is not a data point |

Returning `0.0` for an undefined concentration is forbidden: it is a
legitimate value of the measure and would silently read as perfect equality.
The deployed Q3 already guards this via `nullif(count(*) * total, 0)`; the
same treatment extends to every ratio whose denominator can be zero.

### 7c. Cohort floor guard

A singular test must assert two things.

First, absolutely: no row has `publication_year < gini_cohort_min`. Per §3b a
pre-2012 cohort would produce fabricated zero-citation papers rather than an
error, so this floor is explicit rather than implied by the `where` clause, and
it is never intersected.

Second, that nothing went silently missing above that floor: the minimum
published `publication_year` equals

```text
greatest(gini_cohort_min, year_min)
```

The intersection is required for the same reason as §9b's AI cohort coverage.
The Q3 cohort range is independent of `year_min` / `year_max` (§8), so an
absolute expectation would make this the one Q3 test that constrains which dev
slices can keep the suite green — which §9d step 14 requires and §8 says the
Q3 vars must not do. In prod `year_min` sits far below `gini_cohort_min`, so the
intersected and absolute forms are identical; the intersection removes a false
failure under non-canonical dev slices without weakening the prod guard.

That output guard does not prove that the source still retains the configured
floor. A second Q3-specific source guard must assert that the landed
`counts_by_year` arrays contain at least one entry at the same intersected
floor, `greatest(gini_cohort_min, year_min)`, among the eligible cohort
population. The intersection is required here for the same reason and is not
slack: papers published after the configured floor carry no entries at it, so
an absolute anchor would fail on a dev slice that starts later — a slice
property, not a retention failure. In prod the intersected floor *is*
`gini_cohort_min`, so the check that matters is unchanged; on a later slice it
degrades honestly to "the source retains the floor of what was actually built."
Sparse arrays cannot prove per-paper coverage, but this anchor fails loudly
when the rolling source window has moved wholly beyond the configured floor.
The operational pre-extraction check in §10 remains authoritative.

### 7d. Computation shape

**The age axis is a generated scaffold, not a source projection.** Rows come
from crossing each eligible paper with
`generate_array(1, gini_citation_year_max - publication_year)`, then
left-joining its `counts_by_year` entries. Deriving ages from the entries
themselves would silently drop exactly the rows §3a exists to protect: a paper
with no window citations would vanish instead of contributing a zero, and an
all-zero cell would be an absent row instead of the NULL-measure row §7b
requires. The scaffold is what makes `n_papers` constant across `citation_age`
(§6) and triangle completeness (§9b) true by construction rather than by
accident.

The measures depend only on the *distribution* of `window_citations`, not on
paper identity. Implementation should collapse to value frequencies —
`(grain, publication_year, citation_age, window_citations, n_papers_at_value)`
— before ranking, with zero-citation papers entering as a single synthetic
frequency row of value `0` and count `n_papers - cited_papers`.

For a citation value `v` with frequency `f`, let `r` be the number of papers
with a strictly smaller value and `n` the cell population. The pinned
frequency-form Gini is:

```text
gini = sum(v * f * (2 * r + f - n)) / (n * total_citations)
```

This is the paper-level formula in §5a summed over the tied rank block
`r + 1 .. r + f`. `gini_cited_only` uses the same expression after excluding
`v = 0` and recomputing `r`, `n`, and `total_citations` over cited papers.

**Both sides of that ratio are accumulated in exact `INT64`, with a single
`FLOAT64` division at the end.** This is a pinned requirement, not an
optimization. The numerator equals
`sum over i < j of |x_i - x_j|`, which is half the ordered-pair double sum in
§5a. It is therefore a non-negative integer bounded by
`n * total_citations`; for the largest cell that is on the order of 10^13,
well inside the INT64 range, and individual terms are bounded the same way.
Accumulating it in `FLOAT64` instead would leave roughly
10^-12 to 10^-9 of slack in a quantity of order 1, made non-reproducible by
BigQuery's unspecified aggregation order — which is the same order as the §9b
identity tolerance, comparing two independently accumulated Ginis. Exact
integer accumulation removes the interaction entirely.

The same rule applies to the top-k numerator `sum(v * papers_taken)` and to
the `zero_share` and diagnostic ratios: integer counts and sums first, one
division last.

Top-k shares use descending frequencies. The cutoff paper counts are computed
with integer arithmetic, never a `FLOAT64` percentage:

```text
top1_n  = div(n_papers + 99, 100)
top5_n  = div(n_papers + 19, 20)
top10_n = div(n_papers + 9, 10)
```

These are exactly `ceil(k * n_papers)` for positive integer `n_papers`. For
cutoff `m` equal to the relevant count above, let `r_desc` be the number of
papers with a strictly greater citation value. The number taken from a
value-frequency row is:

```text
papers_taken = min(f, max(m - r_desc, 0))
```

The numerator is `sum(v * papers_taken)`. This pins the boundary allocation
without requiring an arbitrary paper-level order among ties.

This matters more here than it did for the deployed Q3. The paper × age
expansion across a 13-cohort triangle is large, and a naive
`row_number() over (partition by cell order by citations)` would sort whole
cell populations. The frequency form is exactly equal — ties contribute
identically to both the Gini sum and the top-k numerator — and avoids it.

Per-job bytes must be measured against the 100 GiB cap before approval, as in
[Q2 §9d](gold-q2-revisit-design.md#9d-prod-reconciliation).

## 8. dbt configuration

Vars in `dbt_project.yml`:

```yaml
gini_cohort_min: 2012          # earliest rebuildable Q3 publication cohort
gini_citation_year_max: 2025   # latest complete Q3 citation year
# gini_cohort_max              # removed; upper cohort is derived (§3c)
```

`gini_citation_year_max` is independent of `citation_age_year_max`, `year_min`
/ `year_max`, `partial_year`, and `OPENALEX_END_YEAR`. No rollover or
automation may infer it. Advancing it is a manual analytical decision under
§10.

The existing 2012–2016 dev slice limits publication cohorts only.
`stg_works` retains each selected paper's complete `counts_by_year` array, so
dev publishes the full configured lifecycle for those five cohorts: cohort
2012 reaches age 13 and cohort 2016 reaches age 9. Dev is therefore an
analytically faithful preview of prod for the overlapping 2012–2016 rows,
which must reconcile exactly under §9d. It is not a preview of cohorts
2017–2024, which are absent from dev entirely.

The `dbt_project.yml` comment migration is part of this contract:

- the `year_min` / `year_max` block describes corpus bounds and the canonical
  2012–2016 dev **publication slice**, not “the Q3 analytical cohort”;
- the Q3 block describes `gini_cohort_min` and
  `gini_citation_year_max` as independent snapshot bounds and states that the
  upper cohort is derived;
- the Q2 bounds comment links to `docs/gold-q2-revisit-design.md`, not the
  superseded `docs/gold-revisit-design.md` filename.

No extraction, bronze, staging, silver, Terraform, dependency, or IAM change
is required. `silver_works` in particular needs no schema or logic change; its
per-column question attributions do go stale, and that comment repair is listed
in §12.

## 9. Test contracts

Contracts are added to `dbt/models/gold/_gold.yml` before model SQL.

### 9a. Generic model and column tests

Per model:

- an enforced dbt contract with every §6 column and `data_type` declared in
  canonical order;
- unique combination of `cited_group × publication_year × citation_age` or
  `subfield_id × publication_year × citation_age`, respectively;
- non-null on grain columns, `n_papers`, `total_citations`, `zero_share`, and
  `zero_share_including_age0`;
- non-null on the subfield model's display name and two AI-label columns;
- accepted values for `cited_group`: `ai`, `cv_pr`, `rest_cs`;
- `publication_year` within `[gini_cohort_min, gini_citation_year_max - 1]`.
  This is a bound, not an equality, so a dev slice narrower than the Q3 cohort
  range satisfies it unchanged; the §7c guard is what asserts nothing went
  missing at the floor;
- `citation_age >= 1`;
- `n_papers >= 1`;
- `total_citations >= 0`;
- every ratio column within `[0, 1]` where non-null.

### 9b. Singular invariants

- **Decomposition identity.** Where `gini` and `gini_cited_only` are both
  non-null, `abs(gini - (zero_share + (1 - zero_share) * gini_cited_only))`
  is within `1e-9`. Rows with either side null are skipped, not failed. This
  is the strongest invariant in this design: it simultaneously exercises
  ordering, partitioning, zero-paper inclusion, and null handling. The
  tolerance is only safe because §7d pins exact integer accumulation of both
  Gini ratios; under `FLOAT64` accumulation it would be within the noise and
  would have to become a relative bound.
- **Tail monotonicity.** `top1_share <= top5_share <= top10_share` where
  non-null. Per §7b the three are null together, so a null row is skipped
  rather than failed.
- **Triangle completeness.** For every grain cell and publication year, ages
  `1..(gini_citation_year_max - publication_year)` are all present, and no age
  beyond it exists.
- **Fixed cohort size.** `n_papers` is constant across `citation_age` within
  each grain cell and publication year.
- **Cumulative monotonicity.** `total_citations` is non-decreasing in
  `citation_age`, and `zero_share` is non-increasing in `citation_age`, within
  each grain cell and publication year.
- **Age-0 diagnostic order.** `zero_share_including_age0 <= zero_share`.
  Across `citation_age`, `zero_share_including_age0` and non-null
  `age0_citation_share` are both non-increasing within each grain cell and
  publication year.
- **Independent source reconciliation.** Independently derive the complete
  expected cell set from `silver_works` and full-outer-join it to each model,
  so wholly missing cells are failures rather than absent comparison rows.
  For every expected grain × `publication_year × citation_age` cell, reconcile
  `n_papers`, `total_citations`, the window-zero paper count underlying
  `zero_share`, the ages-0..a zero-paper count underlying
  `zero_share_including_age0`, and the age-0 and ages-0..a citation totals
  underlying `age0_citation_share`. The reconciliation query must not reuse
  model result CTEs or a shared metric macro; this is what catches a common
  production filtering or boundary bug.
- **Cross-grain reconciliation.** For every `publication_year × citation_age`,
  `n_papers` and `total_citations` summed across subfields equal the same
  sums across groups, exactly. Both partitions are exhaustive over the same
  silver population, so any discrepancy is a partition bug. Ginis are
  explicitly *not* reconciled — they do not pool (§4a).
- **Unclassified reconciliation.** The `__unclassified__` subfield bucket is
  present exactly when its source population is non-empty, its counts reconcile
  to silver rows with null `primary_topic_subfield_id`, and it is never marked
  strict or broad AI.
- **Subfield label consistency.** In the source, every real `subfield_id` maps
  to *at most* one distinct non-null display name inside the built eligible Q3
  population, so `max` cannot mask conflicting presentation labels. In the
  output, every real `subfield_id` maps to exactly one non-null
  `subfield_display_name` across all cohorts and ages. A subfield with no
  landed display name is not a failure; its entire built series presents as
  its id per §6a.
- **AI cohort coverage.** The pinned `subfield_ai` appears in every publication
  cohort in the **built** range

  ```text
  greatest(gini_cohort_min, year_min) .. least(gini_citation_year_max - 1, year_max)
  ```

  Together with triangle completeness, this guarantees every expected AI
  cohort-age row rather than merely one AI row somewhere in the relation. The
  intersection with the corpus bounds is required, not defensive: the Q3
  cohort range is independent of `year_min` / `year_max` (§8), so under the
  canonical 2012–2016 dev slice an unintersected `2012..2024` expectation
  fails on cohorts that dev cannot contain, and §9d step 14 requires the suite
  green in dev. In prod the intersection is the full `2012..2024`.
- **Cohort floor guard** per §7c.
- **Shared source validity and negative-age diagnostics** per §7a, covering
  the union of the active Q2 and Q3 citation-year ranges.
- **Q3-specific source retention** per §7c. This remains separate because it
  protects the rolling `counts_by_year` floor rather than source-entry
  validity.

### 9c. Deterministic metric unit tests

One dbt unit test is required per final model because a dbt unit test has one
target model. Both override:

```yaml
gini_cohort_min: 2020
gini_citation_year_max: 2023
```

Fixture papers are confined to publication cohort 2020, producing only the
age-1, age-2, and age-3 rows. `format: sql` fixture input is required, and the
`n = 101` population is generated with
`unnest(generate_array(1, 101))` rather than written as literal rows.

Case allocation between the two tests is fixed here, not left to
implementation. The group model has exactly three cells per cohort — `ai`,
`cv_pr`, `rest_cs` — so it cannot host four distinct population sizes, while
the subfield model has as many cells as the fixture declares subfields. The
subfield test therefore carries the population-size, `ceil` rounding,
tie-boundary, all-zero-NULL, and age-0 cases, plus
null-subfield-to-`__unclassified__`. The group test carries `ai` / `cv_pr` /
null-subfield-to-`rest_cs` classification, one cell mixing zero-citation and
cited papers, and the decomposition identity over that cell.

A dbt unit test compares the complete output row set, so `expect` must
enumerate every row the fixture produces — three ages for every declared cell.
Cases are combined into shared cells wherever they do not conflict, rather than
adding one cell per case.

Together the two tests pin the calculation independently of population
invariants. They must cover:

- a cell mixing zero-citation and cited papers, with the zeros affecting
  `gini` but not `gini_cited_only`;
- **ties spanning a top-k cut boundary**, asserting the share is unchanged
  regardless of which tied papers fall inside;
- a `ceil(k * n)` case where the count is visibly not k%, e.g. `n = 101`
  giving 2 papers for `top1_share`;
- exact-boundary cases, one per threshold, asserting no round-up where
  `k * n` is already an integer: `n = 100` pins `top1_n = 1`, `n = 20` pins
  `top5_n = 1`, and `n = 10` pins `top10_n = 1`. Each case pins only its own
  threshold — at `n = 100` the 5% and 10% cutoffs are 5 and 10 papers, not one;
- cumulative window construction across ages, verifying age 0 is excluded
  from `total_citations` but reaches both diagnostics;
- a paper with age-0 citations and none at ages 1..a, asserting it counts as
  window-zero in `zero_share` but not in `zero_share_including_age0`;
- a cell with positive age-0 citations and zero window citations, asserting
  `age0_citation_share = 1.0`;
- an all-zero cell returning NULL rather than 0.0;
- the decomposition identity holding on the fixture's literal values;
- in the group-model test, AI, CV/PR, and null-subfield-to-`rest_cs`
  classification;
- in the subfield-model test, real-subfield preservation and
  null-subfield-to-`__unclassified__` classification.

Expected values in both tests are literal fixture outputs, not recomputed with
the model's own logic.

### 9d. Prod reconciliation

Before approval:

1. Before replacing the prod relation, run the §6a source-label preflight over
   both dev and prod silver populations. Record the number of real subfields
   with more than one distinct non-null display name (expected zero, otherwise
   promotion stops) and the number that will fall back to `subfield_id`.
   After the dev build, verify the output has exactly one non-null published
   label per real subfield.
2. Confirm the published triangle exactly matches `[2012, 2024] ×
   [1, 2025 - y]`, with no absent interior cells and nothing beyond the edge.
3. Run the independent per-cell source reconciliation in §9b for both models,
   including both age-0 diagnostics.
4. Reconcile cross-grain sums and the unclassified bucket per §9b.
5. Verify the decomposition identity across every published row.
6. Recompute `gini`, `zero_share`, `gini_cited_only`, and all three top-k
   shares over ages 0..3 and 0..5, without publishing those alternate
   measures. Record their exact deltas from ages 1..3 and 1..5 at both grains.
   Inspect whether inclusion changes AI's position among real subfields,
   reverses an important pooled comparison, or materially changes a cohort
   trend. This is the age-0 sensitivity analysis; the two published
   diagnostics alone cannot establish neutrality.
7. Record `age0_citation_share` and the difference between `zero_share` and
   `zero_share_including_age0` by group at ages 3 and 5.
8. Run a bounded validation query over the eligible Q3 cohort and record the
   negative-age anomaly count and event weight inside the Q3 read range. This
   is Q3-specific evidence from the shared warning contract, not a duplicate
   permanent test.
9. Inspect all measure series across cohorts for discontinuities, and confirm
   the age-3 and age-5 slices behave consistently.
10. Run the **terminal-edge diagnostic** motivated by the citation-year
    settling risk in §1a. At ages 3 and 5, report the change in every measure
    between the terminal cohort whose window ends in 2025 and the preceding
    cohort whose window ends in 2024, at both grains. Inspect the full triangle
    diagonal whose maximum window ends in 2025 for a common discontinuity.
    This sizes the observed terminal discontinuity, not settling bias: one
    snapshot cannot separate source settling from genuine cohort change. If
    the discontinuity is substantively large, revisit whether the 2025-ending
    cells remain publishable or `gini_citation_year_max` should be 2024.
11. Reconcile every dev row against the corresponding prod row for cohorts
    2012–2016. Fail on missing keys, differing classification flags, or nonzero
    integer-measure deltas; use an explicit tight tolerance for calculated
    ratios. `subfield_display_name` is checked separately under step 1, not
    compared between dev and prod: a name absent from the dev population may
    be supplied by a prod-only cohort to prod's global label mapping.
12. Place AI's Gini within the spread of real individual-subfield Ginis, then
    inspect the pooled relation separately to size the §4b asymmetry.
13. Measure per-job bytes for both models and every test.
14. Run the complete dbt test suite in dev and prod.

Exact values are evidence produced by implementation, not hard-coded
expectations here.

## 10. Freshness and durability contract

Q3 is a **full-corpus analytical snapshot**, on the same terms as [Q2 §11](gold-q2-revisit-design.md#11-freshness-contract),
and is not covered by the automated monthly current-year freshness promise.
Historical citation histories and classifications are not refreshed by the
current-year-only automation.

The fixed window changes the *nature* of Q3's staleness rather than removing
it, and the distinction matters operationally:

- **Mechanical accrual beyond the endpoint is eliminated.** Once a paper's
  window is closed, newly received later citations cannot enter it. This is a
  genuine improvement over cumulative counts, which drift continuously.
  Closed-window values can still change after a full refresh through
  retrospective citation corrections, work merges, corpus changes, or
  primary-topic reclassification. They remain snapshot-dependent rather than
  immutable.
- **Complete citation years are not equally settled.** The landed eligible Q3
  publication shards (2012–2024) were extracted from 2026-05-25 through
  2026-05-29, a roughly four-day spread. That makes cross-cohort timing skew
  within this snapshot negligible, but citation year 2025 had only about five
  months after calendar close for retrospective indexing, versus about
  seventeen months for 2024 and progressively longer for earlier years.
  Windows ending in 2025 therefore form a less-settled edge. The direction of
  any Gini effect is not known in advance because it depends on which papers'
  citations are late-indexed; §9d sizes the observable discontinuity without
  claiming to identify the bias.
- **Source retention is not guaranteed.** `counts_by_year` is a *rolling*
  ~15-year window (§3b). As the corpus advances, its lower bound is expected
  to advance with it. A future full-corpus re-extraction may therefore no
  longer carry citation years 2012–2013 at all, at which point the earliest
  cohorts become unrebuildable rather than merely stale.

The operational consequence: **the earliest cohorts are a fragile edge of the
map, not a permanently recomputable baseline.** Before any full-corpus
re-extraction replaces the landed snapshot, source characterization must
re-verify the observed `counts_by_year` lower bound. The re-extraction may not
be promoted if that check is absent. After landing, the Q3-specific retention
anchor in §7c must also pass. If the lower bound has advanced past 2012,
`gini_cohort_min` must advance with it and the loss of the earliest cohorts
must be recorded explicitly rather than allowed to appear as a silent
shortening of the series.

Advancing `gini_citation_year_max` requires the same four steps as [Q2 §11](gold-q2-revisit-design.md#11-freshness-contract):
deliberate manual full-corpus re-extraction, bronze and upload convergence for
every publication shard, an explicit var change, and a prod rebuild with the
§9d reconciliation.

Automating full-corpus refresh, implementing record-level incremental updates,
and snapshotting early cohorts against window roll-off are all out of scope
for this revision. The last is a real risk that this document names rather
than solves.

## 11. Interpretation and presentation contract

### 11a. Required framing

The four measures answer four sequential questions, and views should present
them in this order:

1. *Is attention more concentrated?* — `gini`
2. *Because many papers receive nothing?* — `zero_share`
3. *Or because attention among noticed papers is unequal?* — `gini_cited_only`
4. *Or because superstar papers capture unusually much?* — top-k shares

Steps 2 and 3 are an exact decomposition of step 1 (§5a) and must be
described as such, not as corroborating evidence. Step 4 is not determined by
that identity.

### 11b. Required caveats

- **The `rest_cs` pooling asymmetry** (§4b) must travel with every pooled
  comparison. `rest_cs` pools many subfields and absorbs between-subfield
  variation that the single-subfield `ai` and `cv_pr` groups cannot. This makes
  the comparison non-like-for-like; it does not guarantee that pooled
  `rest_cs` is higher than every constituent.
- **The age-0 exclusion** (§1b, §5c) must be stated wherever `zero_share` is
  shown, together with the §9d sensitivity finding. The published diagnostics
  describe discarded mass and zero-paper reclassification; they are not
  substitutes for the direct recomputation.
- **The citation-year-settling edge** (§1a, §10) must travel with fixed-window
  cohort trends. Cells whose window ends in 2025 use the least-settled complete
  citation year in the snapshot. This can affect `zero_share` and the
  concentration measures, but the direction of the Gini effect is not known.
  The terminal point must be presented with the §9d endpoint finding and must
  not be interpreted as a cohort trend without that qualification.
- **Incomplete windows are not substituted.** At age 3 the last eligible
  cohort is 2022; at age 5, 2020. Later cohorts have no row at the selected
  age and must not be appended using a shorter window.
- **Truncated heatmap cells** must be unmistakable as unobserved rather than
  low-valued, and must never be compared against complete cells.
- **The `__unclassified__` bucket** is reconciliation-only and must not enter
  AI's rank or position among real subfields.

### 11c. Dashboard shape

The Q3 view leads with **concentration over time among individual
subfields**: a measure series across publication cohorts at the selected
window, placing AI within the distribution of real CS subfields. This is the
default and primary answer to Q3.

The pooled `ai` / `cv_pr` / `rest_cs` comparison is an additional view behind
a grain toggle or secondary control. The two views are separate relations at
different grains, not one filterable table; the control selects the relation.
The pooled view must not be presented as a replacement for the primary
subfield comparison.

The lifecycle heatmap over `publication_year × citation_age` is a **separate
diagnostic view** below the lead series, at group grain, and does not
participate in the toggle. Its ragged upper-right edge is the truncation
boundary and must be rendered as such.

Because zero-share is high at low ages, the `gini` layer of the heatmap
saturates near 1.0 at the left edge. The `zero_share` layer is the more
readable diagnostic there and arguably the more interesting one — "what
fraction of AI papers are still uncited at age 2, by cohort" is a story in its
own right.

Do not describe concentration as a quality, merit, or importance measure. It
combines at least citation practice, venue and preprint culture, subfield
size and growth, and OpenAlex coverage. This is population-level descriptive
analysis over the extracted corpus, not a random sample, so sampling
confidence intervals are not part of the contract.

## 12. Migration and deployment contract

The deployed `gold_citation_gini_by_subfield` is **replaced in place**: same
relation name, new grain and measures. Its current contract is superseded by
this document.

Because the grain changes, the existing `_gold.yml` entry and its tests must
be rewritten rather than extended. No BigQuery relation is dropped — a
`table` materialization replaces the prior table on rebuild — so no cleanup
step comparable to [Q2 §10](gold-q2-revisit-design.md#10-removal-and-deployment-contract) is required.

Existing singular tests and configuration comments are part of the migration,
not invisible carry-over:

- `assert_gold_ai_subfield_present.sql` is rewritten to compare the expected
  cohort set of §9b — `greatest(gini_cohort_min, year_min)` through
  `least(gini_citation_year_max - 1, year_max)` — with distinct AI cohort
  years in `gold_citation_gini_by_subfield`, and fail for every missing
  cohort. Its current “AI exists somewhere” predicate may not remain
  unchanged, and the expectation may not be written as an unintersected
  `2012..2024`, which dev cannot satisfy.
- `assert_citation_age_source_valid.sql` and
  `warn_citation_age_negative_entries.sql` are retained as shared tests but
  their bounded coverage is changed to the Q2/Q3 union in §7a.
- the `dbt_project.yml` comments are migrated exactly as specified in §8;
- `dbt/models/silver/silver_works.sql`'s per-column question attributions are
  repaired. Q3 no longer reads `cited_by_count`, so its
  `-- Q3 (Gini on citation impact)` attribution becomes false; `fwci` is read by
  no model and its `-- Q3 alternative impact measure` attribution likewise;
  `counts_by_year` now serves Q2 **and** Q3, not Q2 alone. Both columns are
  retained. This is a comment repair only — no schema or logic change (§8) —
  and it is carried here because Q3 is what makes the attributions wrong;
- the superseded `docs/gold-revisit-design.md` path is repaired wherever it
  still appears. The file was renamed to `docs/gold-q2-revisit-design.md`.
  Markdown references are repaired during design review; the remaining
  implementation-time references are the comments in `dbt_project.yml`,
  `dbt/models/gold/gold_citation_age_by_year.sql`, and the Q2 model description
  in `dbt/models/gold/_gold.yml`. Q3 carries those repairs because it rewrites
  `_gold.yml` and `dbt_project.yml` anyway. Current-state prose may point to
  this proposed replacement, but must not describe it as deployed before prod
  approval.

After prod reconciliation and approval, the repository documentation is
updated to describe the deployed replacement rather than the superseded Q3:

- `DATA_MODEL.md` records the primary subfield grain and secondary exclusive
  pooled group grain;
- `ARCHITECTURE.md` records both deployed Q3 relations and the fixed-window
  cohort-series contract;
- `STATE.md` updates the deployed Q3 contract, model/test counts, prod evidence,
  freshness limitations, and current work;
- `PLAN.md` moves Q3 from contract decision to completed implementation and
  preserves only genuinely remaining work;
- `README.md` updates the warehouse description and methodology only after the
  replacement results have been validated, without carrying forward findings
  from the superseded cumulative-count model as if they described the new
  metric.

Until that deployment succeeds, current-state documents must continue to
distinguish the deployed 2012–2016 cumulative-count Q3 from this proposed
replacement.

Deployment order:

1. Write contracts and tests in `_gold.yml`.
2. Build and test both models in dev.
3. Run the §9d step-1 display-label preflight over dev and prod silver; stop on
   any conflicting source labels.
4. Build and reconcile in prod per §9d.
5. Confirm Dagster's freshly parsed manifest contains both models.
6. Re-run definitions validation and the warehouse staleness preflight.
7. Reconcile the post-deployment documentation listed above.

The archived gold design is not edited.

## 13. Out of scope

- citing-side analysis of who cites concentrated papers;
- strict/broad composite concentration outputs;
- field-normalized or size-adjusted concentration measures;
- inequality measures beyond Gini and top-k shares;
- statistical inference or confidence intervals on concentration;
- snapshotting early cohorts against `counts_by_year` window roll-off (§10);
- automated full-corpus citation-history refresh;
- changes to Q1 or Q2;
- dashboard implementation.
