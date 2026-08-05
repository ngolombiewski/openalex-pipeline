# Dashboard specification

> **Status: draft for review.** This document pins the proposed dashboard
> contract and staged delivery plan. It does not authorize implementation.

## 1. Purpose and audience

The dashboard is the public-facing analytical conclusion of the repository. It
is a **visual essay**, not a general-purpose exploration or
business-intelligence tool. Its audience is a technically literate visitor who
may know little about OpenAlex and should understand the three findings within a
few minutes.

The default state of every page tells the intended story without interaction.
Controls let a reader inspect the definitions and qualifications that bear on
that story; they do not expose the warehouse as an open-ended query surface.

The dashboard answers exactly the same three questions as the pipeline:

<!-- prettier-ignore -->
| Page | Question | Primary gold relation |
|---|---|---|
| AI output | How has AI's share of CS output changed? | `gold_ai_share_by_year` |
| Citation recency | Has citation attention shifted toward younger work? | `gold_citation_age_by_year` |
| Citation concentration | How are citations distributed within AI and other CS subfields? | `gold_citation_gini_by_subfield` |

`gold_citation_gini_by_group` supplies a secondary Q3 comparison at a different
grain. It is never presented as another filter over the subfield relation.

## 2. Product boundaries

### 2.1 In scope

- A Streamlit application with Overview, AI output, Citation recency, Citation
  concentration, and Methods & data pages.
- A public, unauthenticated Cloud Run deployment from the first waypoint.
- Read-only access to the four production gold relations.
- Fixed, application-owned BigQuery queries followed by in-memory filtering.
- A small number of question-specific controls with explicit defaults.
- Responsive, theme-aware, accessible charts and tabular equivalents.
- Terraform-owned runtime infrastructure, identity, IAM, and cost controls.
- Four independently deployable waypoints, each followed by user review.

### 2.2 Out of scope

- Authentication, passwords, user accounts, invitation links, or saved state.
- A raw-work browser, arbitrary SQL, user-authored queries, or dynamic warehouse
  joins.
- A dashboard selector for dbt target, dataset, or environment.
- Reading staging, silver, raw, GCS, manifests, or local extraction state.
- Triggering extraction, dbt, Dagster, or Terraform from the dashboard.
- Writing to BigQuery or any other external state.
- Treating the reduced dbt dev slice as an analytical preview.
- CSV downloads, user analytics, a custom domain, and automated deployment in
  the first complete version.

## 3. Navigation and page anatomy

The sidebar contains five destinations in this order:

1. Overview
2. AI output
3. Citation recency
4. Citation concentration
5. Methods & data

Only pages delivered by the current waypoint appear. There are no dead links or
"coming soon" placeholders on the public service.

Every analytical page follows the same order:

1. A result-bearing title written as a claim.
2. A short lead sentence stating the default finding.
3. Question-specific controls in a compact row immediately above the visual.
4. One load-bearing primary visual.
5. A short interpretation paragraph containing the qualification that must
   travel with the result.
6. Exact values in an accessible detail table.
7. Optional secondary views or diagnostics.

There are no global analytical controls. "Year" means a publication year in Q1,
a citation-event year in Q2, and a publication cohort plus observation window in
Q3. A global year filter would conflate those meanings.

## 4. Data boundary

### 4.1 Production gold only

The deployed dashboard reads the production dataset `openalex_analytics` only.
The dataset name is pinned by the application and is not runtime-configurable.
The GCP project comes from the existing `OPENALEX_GCP_PROJECT` environment
variable.

Local interactive runs also read production gold through Application Default
Credentials. Automated tests use committed fixtures and make no network or cloud
calls. The dbt dev target is not a dashboard input: its smaller size offers no
useful UI-development advantage, and its Q2 values omit older cited works and
therefore do not represent the production finding.

### 4.2 Relations and query contracts

The dashboard issues one fixed query per relation. Each query:

- names its production table explicitly;
- selects the enforced gold columns explicitly, never `select *`;
- applies no user-derived SQL fragments;
- applies no analytical transformation beyond deterministic ordering;
- sets BigQuery location to `EU`;
- enables the BigQuery query cache; and
- sets `maximum_bytes_billed` to 100 MiB.

All four complete results are small enough to load into memory. Browser
interactions filter and reshape those cached frames and do not issue additional
queries.

<!-- prettier-ignore -->
| Relation | Required columns | Expected production grain |
|---|---|---|
| `gold_ai_share_by_year` | `publication_year`, `variant`, `cs_works`, `ai_works`, `share`, `is_partial_year` | publication year × variant |
| `gold_citation_age_by_year` | `citation_year`, `cited_group`, `citation_events`, `cited_works`, `p25_citation_age`, `median_citation_age`, `p75_citation_age`, `share_age_lte_2`, `share_age_lte_5`, `share_age_lte_10` | citation year × cited group |
| `gold_citation_gini_by_subfield` | `publication_year`, `subfield_id`, `subfield_display_name`, `is_ai_strict`, `is_ai_broad`, `citation_age`, `n_papers`, `total_citations`, `zero_share`, `gini`, `gini_cited_only`, `top1_share`, `top5_share`, `top10_share`, `age0_citation_share`, `zero_share_including_age0` | subfield × cohort × citation age |
| `gold_citation_gini_by_group` | `publication_year`, `cited_group`, `citation_age`, `n_papers`, `total_citations`, `zero_share`, `gini`, `gini_cited_only`, `top1_share`, `top5_share`, `top10_share`, `age0_citation_share`, `zero_share_including_age0` | cited group × cohort × citation age |

The application trusts enforced gold column types and analytical invariants. It
does not reimplement dbt tests. A relation that returns no rows raises a typed
dashboard-data exception because no page can honestly interpret an empty
published result. Query, authentication, and unknown failures otherwise
propagate without fallback to another dataset or stale local data.

### 4.3 Cache and freshness

The final application's four relation loads use one process-local Streamlit data
cache. Earlier waypoints cache only the relations they have delivered. The cache
has:

- a one-hour TTL;
- one cached entry for the complete dashboard snapshot; and
- no disk persistence.

One cache miss performs the four fixed BigQuery jobs. With Cloud Run capped at
one instance, traffic cannot multiply warehouse jobs across an unbounded number
of processes. A failed refresh remains a failure; the application does not
silently substitute an expired snapshot.

The UI describes freshness through the bounds present in gold:

- Q1 visibly identifies the row marked `is_partial_year`.
- Q2 says "Snapshot through citation year {maximum loaded citation year}."
- Q3 says "Citations observed through {maximum cohort + citation age}."

It does not label BigQuery table modification time as analytical freshness.

## 5. Overview page

The Overview is a compact reading path through the three results. Each delivered
question has one panel containing a miniature version of its primary visual, a
one-sentence finding, its relevant time bound, and a link to the full page.

The final Overview contains:

### Q1 panel

- Strict and broad AI-share series from 1980 onward.
- A dashed or otherwise interrupted segment to the partial year.
- Finding: AI's share of CS output is at an all-time high after a long decline
  and renewed rise.

### Q2 panel

- A compact 2012-to-latest comparison of median cited-work age for all three
  groups.
- Finding: by 2025, median citation attention in every group had moved to work
  no more than five years old.

### Q3 panel

- The 2020-cohort, five-year reach-versus-concentration scatter used in the
  README.
- Finding: AI and CV/PR pair relatively broad citation reach with highly
  concentrated winnings among the papers that are cited.

The Overview has no controls. It is a summary, not a second copy of the detailed
pages.

## 6. AI output page (Q1)

### 6.1 Primary visual

A directly labelled line chart plots share of CS works against publication year.
Strict and broad AI appear together by default. Complete years use solid lines;
the segment to the partial year is dashed and ends with a hollow marker.

The default range is 1980 through the latest loaded year. Earlier years are
available through the explicit "Show full history from 1950" control.

### 6.2 Controls

<!-- prettier-ignore -->
| Control | Options | Default | Effect |
|---|---|---|---|
| AI definition | Both, Strict, Broad | Both | Filters the displayed relation variants |
| Historical range | 1980 onward, Full history | 1980 onward | Changes the visible x-domain only |

No count/share switch is provided. Share is the question's measure; exact work
counts belong in the tooltip and detail table.

### 6.3 Tooltip and detail table

Hovering a point shows publication year, definition, AI works, all CS works,
share, and partial-year status. The table below the chart exposes the same
fields for the active definition selection, newest year first.

### 6.4 Required interpretation

The page states that strict AI is OpenAlex subfield 1702, while broad AI also
includes CV/PR subfield 1707. It also states that OpenAlex assigns topics
retroactively using a modern taxonomy: the history shows how today's taxonomy
classifies earlier work, not how each era classified itself.

## 7. Citation recency page (Q2)

### 7.1 Primary visual

The page opens on a directly labelled three-line chart of median cited-work age
by citation year. AI, CV/PR, and rest of CS are mutually exclusive cited-work
groups and all appear by default.

The alternate measure plots the citation-event share going to work no older than
a selected threshold. It uses the same group colours and citation-year axis.

### 7.2 Controls

<!-- prettier-ignore -->
| Control | Options | Default | Effect |
|---|---|---|---|
| Measure | Median cited-work age, Recent-work share | Median cited-work age | Selects the primary y measure |
| Recent threshold | 2, 5, 10 years | 5 years | Selects `share_age_lte_*`; visible only for Recent-work share |
| Cited-work groups | AI, CV/PR, Rest of CS | All three | Filters displayed lines and detail rows |
| Detail year | Every loaded citation year | Latest year | Selects the exact-value table snapshot |

An empty group selection shows an explicit prompt to select at least one group;
it does not silently restore defaults.

### 7.3 Quantile context and detail table

When the median measure is active, selecting exactly one group adds its p25-to-
p75 band. Multiple simultaneous bands are omitted because they obscure the
comparison.

The selected-year table always shows, for each active group:

- citation events and distinct cited works;
- p25, median, and p75 cited-work age; and
- shares aged no more than 2, 5, and 10 years.

### 7.4 Required interpretation

The snapshot bound is displayed beside the title. The text states that events
are classified by the work receiving the citation. The page does not claim to
describe what AI-authored papers cite and does not interpret younger citation
attention as proof of faster intrinsic obsolescence.

## 8. Citation concentration page (Q3)

Q3 contains separate internal views. Subfield and pooled-group results never
share a selector or dataframe.

### 8.1 Subfield snapshot

The default view is a scatter plot with:

- x-axis: `zero_share`, labelled "Share uncited after the selected window";
- y-axis: `gini_cited_only`, labelled "Gini among cited papers";
- one point per classified CS subfield;
- direct labels for AI, CV/PR, Computer Graphics, and Information Systems; and
- AI and CV/PR highlighted without relying on colour alone.

The default is publication cohort 2020 observed over five complete years. This
is the load-bearing view for the headline result.

<!-- prettier-ignore -->
| Control | Options | Default | Effect |
|---|---|---|---|
| Publication cohort | Cohorts present in subfield gold | 2020 | Selects one cohort |
| Complete years observed | Ages available for the selected cohort | 5 | Selects one cumulative ages-1..N window |
| Concentration measure | Cited-only Gini, All-paper Gini, Top 1% share, Top 5% share, Top 10% share | Cited-only Gini | Selects the y-axis metric |

Changing cohort recomputes the valid window options from published cells. If a
previous window is unavailable, the control moves to the largest available
window and displays a short notice. An unavailable cohort/window pair is never
queried or rendered as missing data.

The detail table shows subfield, papers, citations, uncited share, both Ginis,
and all three top-k shares for the selected cell.

### 8.2 Cohort trends

This view compares equally observed publication cohorts. Publication cohort is
the x-axis and a selected metric is the y-axis. The observation window is fixed
across every line; cohorts without that full window are absent by contract.

<!-- prettier-ignore -->
| Control | Options | Default |
|---|---|---|
| Complete years observed | Windows present in gold | 5 |
| Metric | Uncited share, Cited-only Gini, All-paper Gini, Top 1%, Top 5%, Top 10% | Cited-only Gini |
| Subfields | Classified CS subfields, maximum five | AI, CV/PR, Computer Graphics, Information Systems |

The five-subfield limit prevents an unreadable line chart. Attempting a sixth
selection leaves the existing selection unchanged and explains the limit.

### 8.3 Pooled comparison

The pooled comparison reads `gold_citation_gini_by_group` and is visually
separated from the two subfield views. It plots AI, CV/PR, and rest of CS across
publication cohorts at one fixed observation window.

Its controls are observation window and metric; all three groups remain visible
because the purpose is comparison rather than group lookup. The default is the
five-year all-paper Gini, which directly exposes the rejected broad conjecture.

The qualification is always visible: rest of CS pools heterogeneous subfields,
so its Gini contains between-subfield inequality that no individual subfield
carries. This view and the subfield views are two relations at different grains.

### 8.4 Lifecycle heatmap

The heatmap plots the complete observable triangle for one selected subfield:

- rows: publication cohort;
- columns: cumulative complete years after publication;
- cell colour: selected metric; and
- cell tooltip: cohort, observation window, paper count, citation count, and
  exact metric value.

<!-- prettier-ignore -->
| Control | Options | Default |
|---|---|---|
| Subfield | Classified CS subfields | Artificial Intelligence |
| Metric | Uncited share, Cited-only Gini, All-paper Gini, Top 1%, Top 5%, Top 10% | Cited-only Gini |

Unavailable cohort/window combinations remain blank and are labelled in the
legend as "not yet observable"; they are never coloured as zero. Switching
subfield does not rescale colours to that subfield alone. The colour domain is
the observed global min-to-max range for the selected metric across classified
subfields, making the selected heatmaps comparable.

The text states that every window is cumulative ages 1..N, the latest diagonal
ends in citation year 2025, and terminal cells may still be settling.

### 8.5 Age-0 diagnostics

Age 0 is not a global inclusion toggle because gold does not publish every
headline metric under an including-age-0 definition. An expandable diagnostic
section instead shows, for the selected subfield and cohort/window:

- age-0 share of citations received through the selected window;
- uncited share over ages 1..N; and
- uncited share over ages 0..N.

The section explains that publication-year exposure ranges from almost zero to
almost a full year depending on publication month, which is why headline
measures use complete post-publication years.

### 8.6 Required interpretation

The page distinguishes concentration among cited papers from the all-paper Gini,
which also reflects how many papers are uncited. It describes AI's result as the
pairing of high cited-only concentration with relatively broad reach, not as "AI
is the most citation-concentrated part of CS."

`__unclassified__` is excluded from every analytical selector and chart. It is a
reconciliation bucket only.

## 9. Methods & data page

This page is explanatory, not interactive. It contains:

- corpus scope and current bounds;
- strict, broad, and mutually exclusive AI/CV-PR/rest-CS definitions;
- the distinction between publication year, citation year, cohort, and citation
  age;
- the four gold grains;
- Q2's citation-event weighting and cited-side classification;
- Q3's cumulative complete-year windows, uncited-paper inclusion, age-0
  exclusion, and pooled-grain warning;
- the current bounds derived from loaded gold; and
- a link back to the repository's full findings and design rationale.

It does not reproduce reconciliation baselines or internal test counts. Those
remain in `FINDINGS.md`.

## 10. Visual and interaction contract

- Use one stable palette across pages: AI, CV/PR, rest of CS, and neutral
  subfields keep the same identities.
- Pair colour with direct labels, line styles, or point shapes. Colour alone
  never carries identity.
- Use integer formatting for paper counts and citation ages, one decimal place
  for percentages in prose/tooltips, and three decimals for Ginis.
- Chart titles state the population and time/window scope.
- Tooltips expose exact values; prose may use rounded values.
- Every primary visual has an adjacent table representing the active state.
- Controls use presentation names, never raw column names or URL-form subfield
  ids.
- The application follows the active Streamlit light/dark theme.
- Layout remains readable at a single-column mobile width; secondary columns
  stack rather than shrink charts below legibility.
- No smoothing, interpolation, or imputation is applied to annual or triangular
  data.
- No control is added solely because a column exists.

The application does not persist selections or encode them into shareable URLs
in the first version.

## 11. Application structure and contracts

The implementation belongs under `src/openalex_pipeline/dashboard/` and keeps
cloud access separate from presentation:

```text
src/openalex_pipeline/dashboard/
  app.py              Streamlit entry point and navigation
  data.py             fixed queries, BigQuery client seam, cached snapshot load
  models.py           dashboard snapshot and typed dashboard-data exceptions
  charts.py           question-specific chart constructors
  pages/
    overview.py
    q1.py
    q2.py
    q3.py
    methods.py
```

Tests mirror this structure under `tests/dashboard/`. The modules are specific
to these four relations; there is no generic repository, chart registry, page
plugin system, or dashboard framework abstraction.

Public functions receive their data or BigQuery client explicitly. Importing a
page module performs no query. Streamlit owns caching at the application edge;
the data loader itself remains callable and testable without Streamlit or a
network.

Chart constructors return declarative chart objects from supplied in-memory
data. They do not query, cache, read environment variables, or mutate session
state.

The anticipated direct dependencies are Streamlit, Altair, and the BigQuery
Python client. They require explicit approval before implementation because they
are not currently declared in `pyproject.toml`.

## 12. Error behavior

- Missing or empty gold relations raise named dashboard-data exceptions that
  identify the relation.
- An empty user selection produces an inline instruction, not a fallback or a
  stack trace.
- Invalid cohort/window combinations are prevented by the controls.
- Authentication, permission, quota, and unknown BigQuery failures propagate;
  the app never retries against dev or reads a bundled analytical snapshot.
- The public page may present a concise unavailable message for a known
  dashboard-data exception, while preserving the underlying exception in Cloud
  Run logs.

No exception path returns fabricated values, partial relations, or stale data.

## 13. Cloud Run and Terraform contract

### 13.1 Runtime

- Service name: `openalex-dashboard`.
- Region: `europe-west3`.
- Public invocation: `allUsers` receives Cloud Run invoker only.
- Minimum instances: 0.
- Maximum instances: 1.
- Container: 1 vCPU, 512 MiB memory, port 8080.
- The service receives `OPENALEX_GCP_PROJECT`; the production dataset remains
  pinned in code.
- The container runs Streamlit headlessly on `0.0.0.0:8080`.
- No secrets, service-account keys, volumes, or writable persistent storage are
  mounted.

The browser receives no Google credentials. Cloud Run supplies Application
Default Credentials to the server process through the attached runtime service
account.

### 13.2 Runtime identity

Terraform creates a dedicated `dashboard-runner` service account with exactly:

- `roles/bigquery.jobUser` on the project; and
- `roles/bigquery.dataViewer` on the production analytics dataset.

It receives no editor role, no dev-dataset role, no raw-dataset role, and no GCS
role. The service never reuses the dbt runner identity.

### 13.3 Image and deployment

Terraform owns an Artifact Registry repository and the Cloud Run service. The
application image is built from a repository Dockerfile, tagged immutably with
the git commit SHA, and pushed explicitly. Terraform receives that immutable
image reference and creates the corresponding Cloud Run revision.

The initial Artifact Registry bootstrap precedes the first image push; the Cloud
Run resource is applied only after that image exists. Subsequent waypoint
deployments reuse the same public service URL and advance only its immutable
image reference. Continuous deployment is deliberately deferred: a reviewed
waypoint is promoted by an explicit build, push, plan, and apply.

## 14. Verification contract

Automated tests make no network or cloud calls. Each waypoint adds tests before
implementation for the contracts it introduces.

Required coverage includes:

- exact production relation names and explicit selected columns;
- absence of dev, staging, silver, raw, or GCS reads;
- BigQuery job location, query cache, and maximum-bytes settings;
- one injected BigQuery client seam;
- typed handling of missing and empty relations;
- pure transformations from gold rows to each chart/table view;
- default controls and conditional-control visibility;
- partial-year rendering;
- Q2 group and threshold mappings;
- Q3 cohort/window validity and equal-window trend filtering;
- exclusion of `__unclassified__` from analytical views;
- separation of subfield and pooled data paths;
- blank, not zero, heatmap cells outside the observable triangle;
- age-0 diagnostics without a false global inclusion toggle; and
- Streamlit page smoke tests using committed fixtures.

Every waypoint runs at least:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
terraform fmt -check -recursive terraform
terraform validate
```

The container image must build locally. After deployment, a smoke check confirms
that the public service returns successfully and that each delivered page loads
from production gold.

## 15. Delivery waypoints and review gates

No waypoint begins until the previous deployed waypoint has been tested and the
user explicitly authorizes continuation.

### Waypoint 1 — Q1 vertical slice

Deliver:

- approved dependencies and pinned application contracts;
- application shell and delivered-page-only navigation;
- Q1 production-gold loader, cache, fixtures, and tests;
- Overview containing only the Q1 panel;
- complete Q1 page and initial Methods & data page;
- Docker image;
- Artifact Registry, dashboard identity/IAM, and public Cloud Run service; and
- documented explicit deployment commands.

Exit criteria:

- all local checks and container build pass;
- Terraform plan contains only the reviewed dashboard infrastructure;
- the public URL loads Q1 from production gold;
- partial-year and taxonomy qualifications are visible; and
- the user completes hands-on review and authorizes Waypoint 2.

### Waypoint 2 — Q2

Deliver:

- Q2 query, fixtures, transformation contracts, and tests;
- Q2 Overview panel;
- median-age and recent-work-share views;
- controls, quantile context, detail table, and required qualifications; and
- a new immutable image deployed to the existing service.

Exit criteria:

- Q2 production bounds and headline values reconcile with `FINDINGS.md`;
- changing measures, thresholds, groups, and detail year is correct;
- no dev dataset is queried; and
- the user completes hands-on review and authorizes Waypoint 3.

### Waypoint 3 — Q3 core

Deliver:

- separate subfield and pooled queries, fixtures, contracts, and tests;
- final Q3 Overview panel;
- subfield snapshot and equal-window cohort trends;
- separate pooled comparison;
- valid cohort/window controls and exact detail tables; and
- a new immutable image deployed to the existing service.

Exit criteria:

- the default 2020/five-year scatter reconciles with `FINDINGS.md`;
- cohort/window combinations cannot become invalid;
- pooled and subfield paths cannot be mixed;
- the rejected broad conjecture and narrower surviving result are both clear;
  and
- the user completes hands-on review and authorizes Waypoint 4.

### Waypoint 4 — Q3 full and final integration

Deliver:

- lifecycle heatmap and its triangular availability contract;
- age-0 diagnostics;
- terminal-window and pooled-grain caveats;
- completed Methods & data page;
- final cross-page accessibility, mobile, light-theme, and dark-theme pass;
- final README link to the public dashboard; and
- the final immutable image deployed to the existing service.

Exit criteria:

- heatmap cells and colour domains reconcile with production gold;
- unavailable cells cannot be mistaken for zeros;
- both themes and narrow/wide layouts are visually reviewed;
- all repository checks, container build, Terraform validation, and public smoke
  checks pass; and
- the user accepts the completed dashboard.
