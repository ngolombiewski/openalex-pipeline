# PLAN.md — Remaining project work

*Updated: 2026-07-29*

Extraction, bronze, upload, Terraform, dbt staging/silver/gold, and Dagster
orchestration are implemented. Q1, Q3, and orchestration are reviewed and
approved. Q2's replacement is implemented, deployed, prod-reconciled, and
operationally validated. Historical plans and review findings live in git
history; this file contains only work still ahead.

The project workflow remains: discuss the design, pin contracts, write tests,
implement, then review. Do not begin implementation until Nils gives the
signal.

## 1. Review the deployed Q2 result

The reviewed implementation contract is in
`docs/gold-revisit-design.md`. Q2 is an annual, citation-weighted cited-age
comparison at `citation_year × cited_group`, where `cited_group` is `ai`,
`cv_pr`, or `rest_cs`. It covers citation years 2012–2025 as a full-corpus
snapshot; monthly current-year refresh does not extend its freshness.

Dev and prod builds/tests, exact annual reconciliation, anomaly measurement,
analytical inspection, per-job cost measurement, obsolete-relation cleanup,
fresh-manifest validation, and the warehouse preflight are complete. Validated
results and query costs are recorded in `STATE.md`.

Remaining: Nils reviews the deployed result.

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
