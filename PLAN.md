# PLAN.md — Remaining project work

*Updated: 2026-07-31*

Extraction, bronze, upload, Terraform, dbt staging/silver/gold, and Dagster
orchestration are implemented. Q1, the deployed Q3 baseline, and orchestration
are reviewed and approved. Q2's replacement is implemented, deployed,
prod-reconciled, and operationally validated. Historical plans and review
findings live in git history; this file contains only work still ahead.

The project workflow remains: discuss the design, pin contracts, write tests,
implement, then review. Do not begin implementation until Nils gives the
signal.

## 1. Review the deployed Q2 result

The reviewed implementation contract is in
`docs/gold-q2-revisit-design.md`. Q2 is an annual, citation-weighted cited-age
comparison at `citation_year × cited_group`, where `cited_group` is `ai`,
`cv_pr`, or `rest_cs`. It covers citation years 2012–2025 as a full-corpus
snapshot; monthly current-year refresh does not extend its freshness.

Dev and prod builds/tests, exact annual reconciliation, anomaly measurement,
analytical inspection, per-job cost measurement, obsolete-relation cleanup,
fresh-manifest validation, and the warehouse preflight are complete. Validated
results and query costs are recorded in `STATE.md`.

Remaining: Nils reviews the deployed result.

Do not edit the archived gold design.

## 2. Review and deploy the Q3 replacement

The four-round design in `docs/gold-q3-revisit-design.md` is approved for
implementation. Its contracts, two final models, shared paper-window
expansion, deterministic unit fixtures, and singular invariant suite are
implemented and validated on the canonical dev slice. The deployed prod Q3 —
cumulative-count subfield Ginis over the 2012–2016 cohort — remains in place
until review and prod deployment complete.

Decided during design:

- **Fixed citation window replaces cumulative `cited_by_count`.** Ages 1–3
  primary, 1–5 ablation, reconstructed from `counts_by_year`. These are the
  first three or five complete calendar years following the publication year,
  not literally the paper's first three or five years of life.
- **Publication year joins the grain**, so Q3 becomes a cohort series rather
  than a single snapshot. This dissolves the old "which cohort" question.
- **The subfield relation is primary**, rebuilt on the fixed-window metric so
  AI's position among real CS subfields directly answers Q3. A pooled
  `gold_citation_gini_by_group` relation (`ai`/`cv_pr`/`rest_cs`) is added as a
  secondary, structurally asymmetric lens and computed directly because Ginis
  do not aggregate.
- **Null subfields reconcile explicitly.** The subfield relation maps them to
  a fixed `__unclassified__` bucket that participates in reconciliation but
  not in analytical subfield comparisons.
- **Measures:** `gini`, `zero_share`, `gini_cited_only` — an exact
  decomposition, `G = p + (1-p)·G_cond` — plus `top1/5/10_share`, which are
  not determined by that identity, and two explanatory age-0 diagnostics:
  `age0_citation_share` and `zero_share_including_age0`.
- **Age-0 sensitivity is direct, not inferred.** Prod validation recomputes the
  complete measure set over ages 0–3 and 0–5 and records whether the deltas
  alter subfield position, pooled comparisons, or cohort trends. The alternate
  measures do not enter the gold schema.
- **Gold totals reconcile independently to silver.** Both models reconcile
  paper counts, citation totals, zero-paper counts, and diagnostic components
  per published cell; cross-model agreement alone is insufficient.
- **Bounds:** cohorts 2012–2024, ages 1 to `2025 − publication_year`. The full
  observable triangle is published. The 2012 floor is forced by the rolling
  `counts_by_year` window; pre-2012 cohorts would silently fabricate
  zero-citation papers.
- **`citation_age` is the window**, so the 3-vs-5 ablation is a presentation
  slice, not a schema column, and the lifecycle heatmap is the same relation
  with all ages retained.

Open risk named but not solved by the design: `counts_by_year` is a *rolling*
window, so a future full-corpus re-extraction may drop citation years 2012–13
and make the earliest cohorts unrebuildable. See the Q3 design §10.

The latest complete citation year is also the least settled in the snapshot.
The contract retains 2025 but requires a terminal-edge diagnostic and a
presentation caveat; the diagnostic does not identify settling bias.

The canonical dev build publishes the complete lifecycle for cohorts
2012–2016: 605 subfield rows and 165 pooled-group rows. Both model builds, all
Q3 generic and singular tests, and the complete dev dbt suite pass; the
expected shared negative-age warning remains. Dev and prod label preflights
both report zero conflicts and zero fallbacks.

Remaining:

1. Nils reviews the implementation and dev result.
2. Build both relations in prod and run the full §9d reconciliation, including
   age-0 sensitivity, terminal-edge, dev/prod overlap, analytical-position,
   and per-job cost evidence.
3. Validate the fresh Dagster manifest and warehouse staleness preflight.
4. Reconcile ARCHITECTURE, DATA_MODEL, STATE, PLAN, and README with the
   deployed result only after prod validation and approval.

## 3. Streamlit dashboard — not designed

Once its gold inputs are final:

1. Discuss and approve the dashboard story, chart semantics, caveats, filters,
   deployment target, and data-access path.
2. Write the dashboard design and explicit data/UI contracts.
3. Add tests before implementation where practical.
4. Implement the three question views, shared navigation, and
   question-specific group/variant controls.
5. Validate against prod gold outputs, deploy, document operation, and review.

The Q3 view leads with the per-subfield concentration series across publication
cohorts. A secondary grain toggle exposes the pooled `ai` / `cv_pr` /
`rest_cs` relation — two relations at different grains, not one filterable
table. Below it sits the lifecycle heatmap
(`publication_year × citation_age`), a separate group-grain diagnostic view
that does not participate in the toggle. Presentation contract, including the
required caveats on `rest_cs` pooling, age-0 exclusion, incomplete windows,
citation-year settling, and truncated heatmap cells, is
`docs/gold-q3-revisit-design.md` §11.

The dashboard must visibly distinguish the partial current publication year,
label Q2 as a snapshot through citation year 2025, and not describe Q3
subfield comparisons as pooled AI-vs-rest results.

## 4. Final project closeout

- Run the complete Python, dbt, Dagster, and dashboard verification suite.
- Verify the deployed dashboard and refresh path end to end.
- Reconcile README, ARCHITECTURE, STATE, and operational instructions with the
  final code and deployment.
- Record any intentionally deferred analytical work explicitly.
