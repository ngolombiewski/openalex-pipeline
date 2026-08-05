# Dashboard spec

> **Status: preliminary observations only.** This is not the reviewed dashboard
> specification and does not authorize implementation. It records constraints
> discovered during the gold-readiness audit so they survive until the proper
> specification pass.

## Gold inputs

The dashboard can consume the four gold relations directly. Q3's two relations
answer different analytical questions and must not be merged into one
filterable dataset.

<!-- prettier-ignore -->
| Question | Relation | Grain | Preliminary role |
|---|---|---|---|
| Q1 — AI's share of CS works | `gold_ai_share_by_year` | `publication_year × variant` | Historical strict/broad ablation series |
| Q2 — Citation-weighted age of cited works | `gold_citation_age_by_year` | `citation_year × cited_group` | Snapshot comparison of cited-work age distributions |
| Q3 — Citation concentration (primary) | `gold_citation_gini_by_subfield` | `subfield_id × publication_year × citation_age` | Like-for-like CS subfield comparison |
| Q3 — Citation concentration (secondary) | `gold_citation_gini_by_group` | `cited_group × publication_year × citation_age` | Pooled AI/CV-PR/rest-CS comparison |

All four relations have enforced dbt contracts. Their columns and types are the
dashboard's warehouse interface; dashboard code should not reach through gold
into silver or staging.

## Presentation constraints to carry forward

- Q1 must visibly distinguish the configured partial publication year and
  explain that historical topics are assigned retrospectively using the modern
  OpenAlex taxonomy.
- Q2 must be labeled as a snapshot through its configured citation-year maximum,
  not as a live metric. Its groups classify the cited work; the result says
  nothing about the reference choices of AI-authored papers.
- Q3 subfield comparisons and pooled-group comparisons are separate views.
  `rest_cs` pools heterogeneous subfields and includes between-subfield
  inequality that no individual subfield carries.
- Q3 must explain the exclusion of publication-year citations (age 0), the
  cumulative `citation_age` window, incomplete lifecycle triangles, the
  terminal citation-year settling caveat, and any visually truncated heatmap
  cells.
- `__unclassified__` is a reconciliation bucket, not an analytical subfield.

## Decisions deliberately deferred

The reviewed specification still needs to choose the dashboard framework and
query boundary, page and navigation structure, chart forms, default filters,
interaction model, caching, deployment, and the exact placement and wording of
caveats. No UI layout or implementation architecture is pinned here.
