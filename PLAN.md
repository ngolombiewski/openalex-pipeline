# PLAN.md — Remaining project work

*Updated: 2026-07-28*

Extraction, bronze, upload, Terraform, dbt staging/silver/gold, and Dagster
orchestration are implemented. Q1, Q3, and orchestration are reviewed and
approved. Q2's replacement direction and snapshot-freshness decision are
approved, its rigorous specification is reviewed, and its local implementation
is complete. Historical plans and review findings live in git history; this
file contains only work still ahead.

The project workflow remains: discuss the design, pin contracts, write tests,
implement, then review. Do not begin implementation until Nils gives the
signal.

## 1. Review and deploy the Q2 replacement

The reviewed implementation contract is in
`docs/gold-revisit-design.md`. Q2 becomes an annual, citation-weighted cited-age
comparison at `citation_year × cited_group`, where `cited_group` is `ai`,
`cv_pr`, or `rest_cs`. It covers citation years 2012–2025 as a full-corpus
snapshot; monthly current-year refresh does not extend its freshness.

Local implementation is complete: model/schema contracts, generic and
singular tests, `gold_citation_age_by_year`, superseded-model removal, Q3 var
renaming, dbt parse/compile, and the local verification suite are green.

Remaining:

1. Nils reviews the local implementation.
2. Build and test on dev for structure.
3. Build, reconcile, and analytically inspect on prod.
4. Remove only the obsolete Q2 relations from the dev and prod datasets.
5. Validate the deployed Dagster definitions and warehouse preflight.
6. Update result-bearing documentation with the validated prod findings.
7. Review the deployed result.

Do not edit the archived gold design.

## 2. Decide the remaining Q3 contract

Q3 still publishes CS-subfield Ginis over the age-controlled 2012–2016 cohort.
Its subfield statistics cannot be pooled downstream. Decide:

1. Whether to add direct paper-level, variant-grain AI-vs-rest outputs.
2. Whether the age-controlled cohort remains the sole view or gains a
   separately interpreted recent view.
3. Whether and how the cohort's cumulative citation counts should be refreshed.
4. Whether subfield-grain outputs remain alongside a pooled headline.

Write and approve the Q3 addition to the active gold-revisit design before
implementation.

## 3. Streamlit dashboard — not designed

Once its gold inputs are final:

1. Discuss and approve the dashboard story, chart semantics, caveats, filters,
   deployment target, and data-access path.
2. Write the dashboard design and explicit data/UI contracts.
3. Add tests before implementation where practical.
4. Implement the three question views, shared navigation, and
   question-specific group/variant controls.
5. Validate against prod gold outputs, deploy, document operation, and review.

The dashboard must visibly distinguish the partial current publication year,
label Q2 as a snapshot through citation year 2025, and not describe Q3
subfield comparisons as pooled AI-vs-rest results.

## 4. Final project closeout

- Run the complete Python, dbt, Dagster, and dashboard verification suite.
- Verify the deployed dashboard and refresh path end to end.
- Reconcile README, ARCHITECTURE, STATE, and operational instructions with the
  final code and deployment.
- Record any intentionally deferred analytical work explicitly.
