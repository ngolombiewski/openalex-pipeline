# PLAN.md — Remaining project work

*Updated: 2026-07-17*

Extraction, bronze, upload, Terraform, dbt staging/silver/gold, and Dagster
orchestration are implemented, reviewed, and approved. Historical plans and
review findings live in git history; this file contains only work still ahead.

The project workflow remains: discuss the design, pin contracts, write tests,
implement, then review. Do not begin implementation until Nils gives the
signal.

## Decision gate — Q2/Q3 before the dashboard

The current gold layer publishes Q2 and Q3 at CS-subfield grain. It does not
publish pooled AI-vs-rest statistics, because subfield medians and Ginis do not
compose. Its 2012–2016 citation cohort is also outside the current-year-only
refresh policy, so those citation observations can become stale at the source.

**Recommendation:** resolve the Q2/Q3 analytical and refresh contracts before
designing Streamlit. Otherwise the dashboard either overstates what the gold
tables answer or is built against interfaces that are expected to change.

Nils decides whether to accept that recommendation or proceed directly to the
subfield-comparison dashboard.

## 1. Revisit Q2/Q3 gold contracts — pending decision

Design first. At minimum, decide:

1. Whether to add variant-grain pooled AI-vs-rest outputs computed directly
   from paper-level data for half-life and Gini.
2. Whether Q3 remains on the age-controlled 2012–2016 cohort or gains an
   additional, explicitly interpreted view through the current year.
3. Which historical shards must be refreshed to keep citation-derived outputs
   current, and how that broader refresh fits the existing invalidation and
   convergence contracts.
4. Whether the current subfield-grain tables remain published alongside any
   pooled tables.

After approval: write a new active gold-revisit design, pin model contracts,
add dbt tests, implement, build on dev and prod, reconcile, and review. Do not
edit the archived gold design as though it were current.

## 2. Streamlit dashboard — not designed

Once its gold inputs are final:

1. Discuss and approve the dashboard story, chart semantics, caveats, filters,
   deployment target, and data-access path.
2. Write the dashboard design and explicit data/UI contracts.
3. Add tests before implementation where practical.
4. Implement the three question views and shared navigation/variant controls.
5. Validate against prod gold outputs, deploy, document operation, and review.

The dashboard must visibly distinguish the partial current year and must not
describe subfield comparisons as pooled AI-vs-rest results.

## 3. Final project closeout

- Run the complete Python, dbt, Dagster, and dashboard verification suite.
- Verify the deployed dashboard and refresh path end to end.
- Reconcile README, ARCHITECTURE, STATE, and operational instructions with the
  final code and deployment.
- Record any intentionally deferred analytical work explicitly.
