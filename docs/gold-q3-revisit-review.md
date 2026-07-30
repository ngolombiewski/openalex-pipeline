● I read the spec against the deployed models, \_gold.yml, existing singular tests, dbt_project.yml, the archived design, the Q2 doc, and the landed extraction reports. The design is coherent — the decomposition identity checks out algebraically, the triangle bounds are arithmetically consistent, and the null-vs-absent discipline is right. Below is what I'd fix before implementation starts.

# Must resolve (design decisions, not implementation details)

1. The fixed window trades the age confound for a snapshot-settling confound, and the doc never names it.

§1a claims the fixed window "removes the dominant mechanical age confound." It removes accrual, but it introduces a new one directly on the axis this revision exists to create. Citation year 2025 was only ~5 months settled when the corpus was extracted (\_YEAR_REPORT.json shows shards pulled 2026-05-25 → 2026-05-29), while 2024 had ~17 months and 2012 has 13 years of indexing behind it. Every cohort's maximum published age lands on the least-settled year, and at any fixed window the newest eligible cohort is the one whose endpoint is 2025 — at age 3, cohort 2022 closes in 2025 while 2021 closes in 2024. The last point of every trend line is therefore systematically depressed: fewer counted citations → higher zero_share → higher gini. That is a spurious "concentration is rising" signal at exactly the end of the series.

§9d step 8 ("inspect for discontinuities") would surface it but attributes nothing. Needs an explicit decision: either state it in §1a/§10 and add it to §11b's required caveats with a §9d check that sizes the edge effect, or set gini_citation_year_max: 2024 and accept one less cohort. My recommendation is the caveat plus a sized check — dropping a cohort costs real trend length for a bias whose magnitude you can measure.

Good news on the adjacent risk: the shard extraction spread is 4 days, so there is no meaningful cross-cohort snapshot skew. Worth one sentence in §10 recording that, since the "complete calendar year" claim silently depends on it.

> **Assessment:** Partially valid, with one important correction. The differential-settling risk is real: “complete calendar year” does not mean “equally mature in OpenAlex,” and the landed reports confirm that eligible Q3 shards were captured over only four days in late May 2026, so citation year 2025 had much less time for retrospective indexing than earlier years. However, undercounted citations do not mechanically imply a higher Gini. `zero_share` will be biased upward if the missing citations would have reached currently uncited papers, while the direction of the Gini bias depends on which papers' citations are missing. The review therefore overstates the direction and certainty of the resulting signal.
>
> **Proposed fix:** Keep `gini_citation_year_max: 2025`, but add an explicit “citation-year settling” limitation to §1a and §10 and make it a required §11b caveat. Add a §9d endpoint diagnostic that reports the 2025-ending cohort changes against the preceding cohort at ages 3 and 5 for every measure and both grains, and inspects the full triangle's 2025-ending diagonal. Describe this as sizing a possible edge effect, not identifying a causal bias: a single snapshot cannot separate settling from genuine cohort change. Record the four-day eligible-shard extraction spread in §10 to rule out material within-snapshot timing skew. If the terminal discontinuity is substantively large, approval should revisit whether to publish 2025-ending cells or set the bound to 2024.

2. §9c will not build as written without var overrides.

The Q2 unit test pins its window via overrides: vars (\_gold.yml:191-194). Q3's fixture has no such instruction, so it would run against gini_cohort_min: 2012 / gini_citation_year_max: 2025 and every fixture paper would expand across up to 13 ages — the expected-rows block becomes unmanageable and the n = 101 case unwritable. §9c must require overriding both vars to a 1–2 cohort, 2–3 age window, and should state whether generated fixture rows (select ... from unnest(generate_array(1, 101)) in a format: sql given) are acceptable for the ceil(k \* n) case. As written, the implementer has to invent that contract.

> **Assessment:** Valid. The default triangle would make a deterministic fixture needlessly large, and the `n = 101` case should be generated rather than hand-written. There is a second underspecification: a dbt unit test names one target model, while §9c requires classification behavior from both the group and subfield outputs. One fixture cannot directly pin both final models.
>
> **Proposed fix:** Require unit-test var overrides explicitly, for example `gini_cohort_min: 2020` and `gini_citation_year_max: 2023`, with fixture papers confined to one cohort so only ages 1–3 are expected. Permit and require `format: sql` plus `unnest(generate_array(1, 101))` for the top-1% rounding case. Specify one deterministic unit test per final model, sharing the same metric cases where useful: the group test pins `ai` / `cv_pr` / null-to-`rest_cs`, and the subfield test pins real subfields and null-to-`__unclassified__`.

3. The Q3-scoped source tests in §7a.3–4 and §9b are fully redundant with tests already deployed.

assert_citation_age_source_valid.sql already fails on null years anywhere in any array, and on null counts, negative counts, and duplicate work × year entries for citation years [citation_age_year_min, citation_age_year_max] = [2012, 2025]. warn_citation_age_negative_entries.sql already warns on the negative-age class over the same range. Q3's read range is citation years [2012, 2025] — identical, not a superset. So all three proposed Q3-scoped tests duplicate existing coverage exactly under current vars, which cuts against "trust the layer below within its scope."

Decide explicitly: either drop them and cite the Q2 tests as covering Q3's range, or keep them solely as var-drift insurance and say so in the doc. Right now an implementer following §9b writes three redundant tests without knowing they're redundant. (The §7c source-retention anchor is genuinely new and should stay.)

> **Assessment:** Valid for the current configuration, but not durably valid if the design merely cites the Q2 bounds. `assert_citation_age_source_valid.sql` is a strict superset of Q3's proposed validity checks today, and `warn_citation_age_negative_entries.sql` is a strict population superset of the Q3 warning today. However, §8 deliberately makes `gini_citation_year_max` independent of `citation_age_year_max`; after either bound advances alone, Q2's test range may no longer cover Q3. These are shared source-array contracts over `silver_works`, not question-specific facts, so duplicating the SQL is still the wrong fix.
>
> **Proposed fix:** Retain one shared source-validity test and one shared negative-age warning, and define their citation-year coverage as the union of the active Q2 and Q3 ranges (currently 2012–2025). Remove the proposed duplicate Q3 tests and cite the shared tests in §7a and §9b. Keep §7c's Q3-specific retention anchor. For §9d's Q3-only anomaly count and weight, run a bounded validation query over the eligible Q3 cohort rather than add a second permanent warning test.

# Should fix before implementation

4. §8's dev-slice claim is wrong, and it understates what dev can validate. stg_works filters publication_year only (stg_works.sql:36); counts_by_year is carried whole per work. So the dev slice's cohorts 2012–2016 carry full citation years through 2025 and produce a complete triangle up to age 13 — the upper ages do not "depend on which citation years the slice carries." That makes dev a faithful preview for those five cohorts: dev and prod values should match exactly there, which is a free and strong reconciliation check that §9d currently doesn't claim.

> **Assessment:** Valid. The dev override limits publication cohorts, not entries inside `counts_by_year`; staging preserves each selected paper's complete nested array. Dev therefore publishes the full configured lifecycle for cohorts 2012–2016 (maximum age 13 for 2012, decreasing to age 9 for 2016), not a citation-year-truncated triangle. Because dev and prod read the same landed snapshot and apply the same transformations, their overlapping Q3 rows should agree exactly.
>
> **Proposed fix:** Rewrite §8 to call dev an analytically faithful preview for the five retained cohorts while making clear that it cannot preview cohorts 2017–2024. Add a §9d reconciliation comparing every dev row and measure with the corresponding prod row, failing on missing rows or nonzero deltas (with an explicit floating-point tolerance for calculated ratios).

5. Contract enforcement is unspecified. §6 pins BigQuery types, which implies config: contract: enforced: true plus per-column data_type: as Q2 does (\_gold.yml:45-47), but the doc never says so — and Q1/deployed-Q3 don't enforce contracts, so the precedent is split. State it, and note the §6 table is a union that splits into two per-model column lists (the group model has no subfield_id, display name, or AI labels).

> **Assessment:** Valid. A canonical type table alone is documentation, not dbt enforcement, and the repository has split precedent. Leaving this implicit would let an implementation satisfy the prose while omitting the executable contract.
>
> **Proposed fix:** State in §6 and §9a that both Q3 models use `config.contract.enforced: true` and that every published column has the pinned `data_type` in `_gold.yml`. Split the union table into an explicit ordered column list for each model, or add two unambiguous projections from the shared measure set, so absence of the subfield-only columns from the group contract is mechanically clear.

6. assert_gold_ai_subfield_present.sql isn't mentioned in §12. It still compiles under the new grain, which is the hazard: it will silently degrade from "AI is present" to "AI is present in at least one cohort-age cell." Under the new grain it should assert AI appears in every published cohort. §12 mentions rewriting only the \_gold.yml entry.

> **Assessment:** Valid. The existing singular test survives compilation but becomes too weak at the new grain. The independent source reconciliation in §9b should catch missing AI cells when AI exists in silver, but it does not make the stale test harmless or pin the stronger analytical expectation that AI is represented in every configured cohort.
>
> **Proposed fix:** Add existing singular tests to §12's migration inventory. Rewrite `assert_gold_ai_subfield_present.sql` to compare the complete expected cohort set `gini_cohort_min..gini_citation_year_max - 1` with distinct AI cohort years in the subfield model and fail for every missing cohort. Together with triangle completeness, cohort presence then implies every expected AI cohort-age row. Alternatively remove the old test explicitly if the independent source reconciliation is chosen as the sole contract; do not leave it unchanged.

7. §7d states the frequency form is "exactly equal" but never pins the expression. Given "contracts before tests before implementation," and given that the paper-level formula is pinned in §5a, the doc should carry the form that will actually be implemented. For value v with frequency f and r papers holding strictly smaller values, out of n:

contribution = v _ f _ (2r + f - n)

summed over values, divided by n _ total_citations. That's algebraically identical to sum((2i - n - 1) _ x_i) and it's the line the implementer would otherwise have to derive and you'd have to re-verify at review.

> **Assessment:** Valid. The proposed expression is algebraically correct: summing the paper-level coefficient over the tied rank block `r + 1 .. r + f` yields `f * (2r + f - n)`. Pinning it removes an unnecessary derivation from implementation review.
>
> **Proposed fix:** Add the frequency-form Gini contract to §7d using unambiguous multiplication signs:
>
> `gini = sum(v * f * (2 * r + f - n)) / (n * total_citations)`
>
> where `r` is the cumulative frequency of strictly smaller values. State that `gini_cited_only` uses the same expression after excluding `v = 0` and recomputing `r` and `n` over cited papers. Also pin the frequency-boundary allocation used by top-k shares, since §7d relies on the same equivalence there.

8. dbt_project.yml comments go stale in two places. The year_min/year_max block calls the dev slice "the Q3 analytical cohort," and the gini block says "Q3 age-controlled publication cohort. Same bounds as the canonical dev slice." Both become false. §8 shows the new var block but not the comments.

> **Assessment:** Valid. Both comments would contradict the revised cohort-series contract even though the YAML values themselves are changed correctly. The nearby Q2 design link also still names `docs/gold-revisit-design.md`, while the active file is now `docs/gold-q2-revisit-design.md`.
>
> **Proposed fix:** Make §8 require the accompanying comment migration: describe `year_min` / `year_max` as corpus bounds with a canonical 2012–2016 dev publication slice; describe `gini_cohort_min` and `gini_citation_year_max` as independent Q3 snapshot bounds, with the upper cohort derived; and update the Q2 link to the active filename.

---

# Review round 2

Read against the deployed models, `_gold.yml`, the singular tests,
`dbt_project.yml`, `stg_works` / `silver_works`, and the Q2 design. All eight
round-1 findings are correctly folded in. The core mathematics verifies:
`G = p + (1 - p) * G_cond` is exact for the `sum((2i - n - 1) * x) / (n * sum(x))`
estimator, and `v * f * (2r + f - n)` is its correct tied-block form. The
triangle arithmetic, the null-versus-absent discipline, and §8's dev-preview
claim all hold — `stg_works` filters publication year only and carries
`counts_by_year` whole, so the §9d dev/prod exact reconciliation is achievable.

Three findings block implementation, three should be settled before it starts.

## Must resolve

9. The AI cohort coverage test cannot pass in dev.

§9b and §12 require `subfield_ai` in every cohort from `gini_cohort_min`
through `gini_citation_year_max - 1` — 2012 through 2024 — as an absolute set.
The canonical dev slice overrides `year_max: 2016`, so cohorts 2017–2024 do not
exist in `silver_works` at all, while §9d step 13 requires the complete suite
green in dev. Every other Q3 test is scoped to published cells and survives the
slice; this one is not. §8 makes the Q3 cohort range deliberately independent
of `year_min` / `year_max`, which is what creates the gap.

> **Assessment:** Valid and blocking. The independence of the two var pairs is
> a deliberate design property, so the test must intersect them rather than
> assume they agree.
>
> **Applied fix:** §9b now expects AI in the *built* cohort range
> `greatest(gini_cohort_min, year_min) .. least(gini_citation_year_max - 1, year_max)`,
> with the reason recorded inline so the intersection is not later mistaken for
> defensive slack. §12 carries the same bound into the
> `assert_gold_ai_subfield_present.sql` rewrite and explicitly forbids the
> unintersected `2012..2024` form. In prod the intersection is the full range.

10. The decomposition-identity tolerance is unsafe under `FLOAT64` accumulation.

§9b pins `abs(gini - (zero_share + (1 - zero_share) * gini_cited_only))` within
`1e-9`. For `rest_cs` the Gini numerator is of order `n * total_citations`,
around 10^13, so `FLOAT64` accumulation leaves roughly 10^-12 to 10^-9 of slack
in a quantity of order 1 — the same order as the tolerance — and BigQuery's
aggregation order is unspecified, so the residual is not reproducible. The test
compares two independently accumulated Ginis, which compounds it. This is a
contract decision, not an implementation detail: §7d pins the formula but not
its arithmetic type.

> **Assessment:** Valid and blocking. The numerator equals
> `sum_i sum_j |x_i - x_j|`, a non-negative integer bounded by
> `n * total_citations`, so the largest cell sits around 10^13 — three orders of
> magnitude inside `INT64`. Exactness is available for free; the weaker
> alternative is a looser relative tolerance on the strongest invariant in the
> design.
>
> **Applied fix:** §7d now requires both sides of every Gini ratio to be
> accumulated in exact `INT64` with a single `FLOAT64` division last, with the
> bound argument stated, and extends the rule to the top-k numerator and the
> `zero_share` and diagnostic ratios. §9b records that the `1e-9` tolerance is
> only safe because of that pin.

11. The non-null `subfield_display_name` contract is an unverified bet.

§6 pins the column non-null under an enforced contract and §9b asserts exactly
one non-null display name per real `subfield_id`. The value comes from
`json_value(primary_topic, '$.subfield.display_name')` in `stg_works` with no
upstream non-null or single-value guarantee, and the deployed Q3 carries no
`not_null` test on it. If either assumption is false in prod, the enforced
contract fails the build rather than reporting the anomaly.

> **Assessment:** Valid. The design asserts a data property it has not
> verified, and enforces it in the one place where being wrong is a hard
> failure rather than a finding.
>
> **Applied fix:** New §6a. The published value is
> `coalesce(any_value(display_name), subfield_id)`, so a missing label presents
> as the id — visibly odd, never null, never a build failure. Conflicting
> labels remain a test failure, not a silent `any_value` pick, so §9b's
> label-consistency test is restated as *at most one distinct non-null*
> display name. New §9d step 14 requires reporting the conflict count and the
> coalesce-fallback count from dev before the contract is enforced in prod.

## Should fix before implementation

12. §7a rule 1 under-specifies the window, and the age scaffold is unpinned.

Rule 1 bounded entries by `gini_citation_year_max` alone; the per-row cap at
`publication_year + citation_age` appeared only inside §2's formula. Separately,
nothing pinned that rows originate from a generated age scaffold rather than
from `counts_by_year` entries — and that distinction is exactly what makes
§3a's zero-citation papers survive. Deriving ages from entries would drop the
papers the design exists to keep and turn all-zero cells into absent rows
instead of the NULL-measure rows §7b requires. Both are inferable from the
document as a whole, which is precisely the kind of derivation "contracts
before tests before implementation" is meant to remove.

> **Applied fix:** §7a rule 1 now states the per-row window explicitly as
> `[publication_year + 1, publication_year + citation_age]` and marks
> `gini_citation_year_max` as the read-range and triangle bound only. §7d opens
> with the scaffold requirement — cross each eligible paper with
> `generate_array(1, gini_citation_year_max - publication_year)`, then left-join
> its entries — and records that the scaffold is what makes constant `n_papers`
> and triangle completeness true by construction.

13. The migration inventory misses the superseded Q2 design path.

§8 migrates the `dbt_project.yml` comments, but `docs/gold-revisit-design.md`
was renamed to `docs/gold-q2-revisit-design.md` and the dead name still appears
in `gold_citation_age_by_year.sql`, the Q2 model description in `_gold.yml`,
`README.md`, `ARCHITECTURE.md`, and `STATE.md`.

> **Applied fix:** §12 adds the path repair to the migration inventory with the
> full site list, and states why Q3 carries it rather than deferring: Q3
> rewrites `_gold.yml` and `dbt_project.yml` anyway, and shipping a design that
> cites a path the repository contradicts is worse than a one-line chore.
> `ARCHITECTURE.md` is edited for this repair only.

14. §6's anti-intermediate stance left a cost question open.

Both models need the identical paper-by-age window expansion, and §6 permitted
an intermediate model only on a "separately testable contract" argument —
leaving the implementer to weigh a duplicate scan without a budget. Q2's
comparable scan billed 1.5 GiB against the 100 GiB per-job cap, so the
duplication is immaterial and the question should not reach implementation at
all.

> **Applied fix:** New §6b explicitly authorizes a shared macro for the
> expansion, accepts the duplicate pass on the recorded Q2 cost evidence, and
> retains the separately-testable-contract bar as the only justification for an
> intermediate model.

## Noted, no change required

- Nothing in the Python or Dagster layer references gold model names, so adding
  `gold_citation_gini_by_group` is a manifest-only change. `STATE.md`'s
  "5 models, 60 data tests, 1 unit test" counts will move.
- `cited_group` is a loose name at this grain: Q3 has no citing side, and an
  uncited paper still carries one. Kept for cross-question symmetry with Q2;
  §4 now requires the model docstring to say the column classifies the paper by
  its own subfield, not by any citation relationship.

---

# Review round 3

Round two's built-range AI test, generated age scaffold, shared source
validation, and exact Gini accumulation hold. Five lingering findings were
accepted and folded into the design.

## Must resolve

15. Display-name fallback did not guarantee a stable label across cohorts.

`coalesce(any_value(display_name), subfield_id)` at cohort-age grain could
publish a real name in one cohort and the id fallback in another while the
source conflict test still passed.

> **Applied fix:** §6a now requires one deterministic label mapping per
> `subfield_id` over the complete built eligible population:
> `coalesce(max(display_name), subfield_id)`. That mapping is joined to every
> cohort-age row. Source conflicts remain failures, and a new output invariant
> requires exactly one non-null published label per real subfield. The design
> also corrects the prior rationale: dbt contract enforcement pins column
> shape and type here; the generic `not_null` test is value-level and runs
> after materialization. Label characterization now covers both dev and prod
> silver before prod replacement, and dev/prod metric reconciliation excludes
> the presentation label because their built label populations differ.

16. Top-k cutoff arithmetic was not pinned exactly.

The design required integer accumulation for ratios but left
`ceil(k * n_papers)` open to a `FLOAT64` implementation.

> **Applied fix:** §7d pins exact integer cutoffs with `div(n + 99, 100)`,
> `div(n + 19, 20)`, and `div(n + 9, 10)`. §9c adds exact-boundary cases at
> `n = 100`, `20`, and `10` alongside the existing `n = 101` rounding case.

## Should fix

17. Post-deployment documentation reconciliation was missing.

Round two noted that model and test counts would move but required no change,
which conflicts with `STATE.md` being the current source of deployed state.

> **Applied fix:** §12 now requires post-deployment reconciliation of
> `DATA_MODEL.md`, `ARCHITECTURE.md`, `STATE.md`, `PLAN.md`, and `README.md`.
> Current-state documents were updated now to distinguish the deployed
> cumulative-count Q3 from the proposed fixed-window replacement without
> claiming deployment.

18. §7d's exact-arithmetic explanation had a factor-of-two error.

The pinned numerator is the sum over unordered pairs, not the full ordered-pair
double sum.

> **Applied fix:** §7d now states
> `sum over i < j of |x_i - x_j|`, equivalently half the ordered-pair sum in
> §5a. The formula and INT64 bound are unchanged.

19. The endpoint diagnostic still attributed more than it could identify.

One snapshot can measure the terminal discontinuity but cannot isolate
citation-year settling from genuine cohort change.

> **Applied fix:** §9d calls it the **terminal-edge diagnostic** and states
> explicitly that it sizes the observed discontinuity, not settling bias. The
> decision to retain citation year 2025 and carry the settling caveat is
> unchanged.

---

# Review round 4

Read against the deployed models, `_gold.yml`, `dbt_project.yml`, the twelve
singular tests, `stg_works` / `silver_works`, the Q2 design, and `STATE.md`.
All nineteen prior findings are correctly folded in.

**No blocking issues.** The design is implementable as written. Six precision
items were found and all six are applied below.

Verified independently this round:

- `G = p + (1 - p) * G_cond` is exact for the pinned estimator, checked on
  worked cases; `v * f * (2r + f - n)` is its correct tied-block form; round
  three's `sum over i < j` correction is consistent with §5a's `2 n^2 mu`
  denominator.
- `div(n + 99, 100)`, `div(n + 19, 20)`, `div(n + 9, 10)` are exactly
  `ceil(k * n)`; top-k monotonicity and every §9b monotonicity invariant follow
  from non-negative counts plus the §7d scaffold.
- The `INT64` bound holds for individual terms as well as the sum:
  `|v * f * (2r + f - n)| <= v * f * n`, and `sum(v * f) = total_citations`, so
  no partial sum can exceed `n * total_citations`.
- `silver_works` carries `counts_by_year`,
  `primary_topic_subfield_display_name`, and both AI flags, so §8's "no silver
  change" holds. `stg_works` filters publication year only and keeps
  `counts_by_year` whole, so §9d step 11's exact dev/prod reconciliation is
  achievable.
- `overrides: vars` in a dbt unit test is proven by the deployed Q2 test.
- The three surviving `docs/gold-revisit-design.md` references are exactly the
  three sites §12 names. `gini_cohort_max` appears only in `dbt_project.yml`
  and the model it replaces. All four cross-document anchors into the Q2 design
  resolve. Q2's recorded 1.5 GiB scan supports §6b's cost argument.

## Should fix

20. `silver_works.sql`'s per-column question attributions go stale.

`cited_by_count` is commented `-- Q3 (Gini on citation impact)` and `fwci`
`-- Q3 alternative impact measure`, but the revised Q3 reads neither — it reads
`counts_by_year`, which is commented as Q2's alone. §8 said no silver change was
required and §12's inventory omitted the file, so these would survive as false
comments in the layer Q3 now depends on most. Same class as round one's
finding 8.

> **Applied fix:** §12 adds the comment repair with the specific attributions,
> and §8 now says `silver_works` needs no *schema or logic* change while
> pointing at §12 for the comments. Both columns are retained.

21. §7d's `INT64` headroom claim is off by roughly three orders of magnitude.

The numerator is on the order of 10^13 against an `INT64` maximum of about
9.2 * 10^18 — six orders of headroom, not the three claimed. The conclusion is
unaffected and in fact stronger, but it is a wrong number in a pinned
rationale that gets re-verified at review.

> **Applied fix:** §7d now says "well inside the INT64 range"; the bound
> argument is unchanged.

22. §9c's exact-boundary bullet is false as literally written.

It asserted that `n = 100`, `20`, and `10` make the 1%, 5%, and 10% cutoffs
"take exactly one paper." At `n = 100` only the 1% cutoff is one paper; the 5%
and 10% cutoffs are 5 and 10.

> **Applied fix:** §9c restates the cases as one `n` per threshold — `n = 100`
> pins `top1_n = 1`, `n = 20` pins `top5_n = 1`, `n = 10` pins `top10_n = 1` —
> and names the `n = 100` misreading explicitly.

23. §9c left case allocation between the two unit tests to inference.

The list is introduced with "together the two tests" and only two bullets are
model-tagged, but the group model has exactly three cells per cohort, so it
cannot host four distinct population sizes. The implementer had to discover
that constraint and invent the split.

> **Applied fix:** §9c pins the allocation and states the three-cell reason.
> The subfield test carries the population-size, rounding, tie-boundary,
> all-zero-NULL, and age-0 cases plus `__unclassified__`; the group test
> carries classification, one mixed cell, and the identity. §9c also records
> that a dbt unit test compares the complete output row set, so `expect` must
> enumerate three ages per declared cell and cases share cells rather than each
> adding one.

24. §7c's cohort floor guard repeated the shape round two fixed in §9b.

It asserted `min(publication_year) = gini_cohort_min` absolutely — the same
unintersected form round two rejected for AI cohort coverage, for the same
reason. It passes today only because prod's `year_min` is 1950 and the
canonical dev slice's is 2012. Any dev slice starting later fails it for a
non-defect, making it the one Q3 test that constrains which slices can satisfy
§9d step 14.

> **Applied fix:** §7c is split into two assertions. The hard floor — no row
> below `gini_cohort_min`, the §3b guard against fabricated zero-citation
> papers — stays absolute and is explicitly never intersected. The
> nothing-went-missing half becomes
> `greatest(gini_cohort_min, year_min)`, with the §9b rationale recorded
> inline and the note that in prod both forms are identical, so the prod guard
> is not weakened. The §7c source-retention anchor is unchanged.

25. §3a's "configured publication-year range" was ambiguous.

`year_min` / `year_max` are literally the configured publication-year bounds in
`dbt_project.yml`, while §6 pins the model's filter to the Q3 cohort range.
Resolvable from context, but it is exactly the derivation "contracts before
tests before implementation" exists to remove.

> **Applied fix:** §3a names the filter as
> `[gini_cohort_min, gini_citation_year_max - 1]`, states that it is not the
> corpus bounds, and records that the built population is the intersection of
> the two — which is why §9b's coverage expectations are intersected.

26. Correction to finding 24: the §7c retention anchor shares the same defect.

Finding 24 was scoped on the claim that the retention anchor was unaffected.
That was wrong. The anchor asserts the landed `counts_by_year` arrays carry an
entry at `gini_cohort_min` *among the eligible cohort population*, and papers
published after that floor carry no entries at it — so on a dev slice starting
later it fails on a slice property, not a retention failure, exactly like the
half that finding 24 fixed.

> **Applied fix:** the anchor is intersected the same way, to
> `greatest(gini_cohort_min, year_min)`, with the reason recorded inline. In
> prod the intersected floor *is* `gini_cohort_min`, so the check that matters
> — has the rolling source window moved past the configured floor — is
> unchanged; on a later slice it degrades honestly to "the source retains the
> floor of what was actually built."

## Consistency pass

A full end-to-end read of the design after the six fixes landed. Five further
items, all applied:

- §1 item 4 called the new measure set a "four-part decomposition plus tail
  shares," contradicting §5a (three measures form the identity; top-k is
  explicitly *not* determined by it) and §11a's four sequential questions. Now
  reads "a three-part decomposition (§5a), tail shares, and two age-0
  diagnostics."
- §3c stated the `[2012, 2024]` cohort bounds absolutely. Now records that
  those are the prod triangle at current vars and that a dev slice builds their
  intersection with `year_min` / `year_max`, while each built cohort's age
  range is unaffected because `stg_works` carries complete `counts_by_year`.
- §9a's `publication_year` test said "within the configured range" — the same
  ambiguity finding 25 removed from §3a. Now names
  `[gini_cohort_min, gini_citation_year_max - 1]` and records that it is a
  bound, not an equality, so a narrower dev slice satisfies it and §7c is what
  asserts nothing went missing at the floor.
- §9b's tail monotonicity did not state null handling, unlike the
  decomposition identity beside it. Now "where non-null," noting per §7b the
  three shares are null together.
- Line-wrap and list-indent repairs in §7d and §9d step 12.

## Noted, no change required

- The deployed `gini_cited_only <= gini` model test is subsumed by the
  decomposition identity at the new grain. §12's "rewritten rather than
  extended" already covers dropping it.
