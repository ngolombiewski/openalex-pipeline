# Dashboard specification

> **Status: revised draft for review.** This document pins the proposed dashboard
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
- Terraform-owned runtime infrastructure, identity, IAM, and the spend guards
  named in §13.4.
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

1. A title stating the result and its scope in the default state, or describing
   the active comparison after controls change.
2. A short lead sentence interpreting the displayed data.
3. Question-specific controls in a compact row immediately above the visual.
4. One load-bearing primary visual.
5. A short interpretation paragraph containing the qualification that must
   travel with the result.
6. Exact values in an accessible detail table.
7. Optional secondary views or diagnostics.

There are no global analytical controls. "Year" means a publication year in Q1,
a citation-event year in Q2, and a publication cohort plus observation window in
Q3. A global year filter would conflate those meanings.

Numerical claims, extrema, and rankings come from the loaded rows. Ties are
described as ties. Q1 record claims compare the full loaded history, separately
for each definition and for complete versus partial years; changing the visible
range does not change that comparison. If refreshed data no longer supports a
prescribed finding, show the current descriptive values without the old claim.
Q3's reviewed interpretation is explicitly scoped to the default 2020/five-year
cell and cited-only measure. Other selections receive descriptive titles and
values rather than inheriting that conclusion.

## 4. Data boundary

### 4.1 Production gold only

The deployed dashboard reads the production dataset `openalex_analytics` only.
The dataset name is pinned by the application and is not runtime-configurable.
The GCP project comes from the existing `OPENALEX_GCP_PROJECT` environment
variable.

Local interactive runs also read production gold through Application Default
Credentials — the developer's own ADC identity directly, with no impersonation.
Automated tests use committed fixtures without network or cloud calls. Dev is
not a dashboard input: its Q2 values omit older cited works and do not represent
production.

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

Loaded relations are **pandas** frames. This is a deliberate local exception to
the repository's Polars idiom, confined to the dashboard package: the BigQuery
client materializes to pandas and Altair consumes it natively, so converting to
Polars and back would add a translation layer that buys nothing. No dashboard
module imports Polars.

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

One cache miss performs one fixed BigQuery job per delivered relation. Cache
only a fully loaded batch. Failed refreshes propagate without substituting an
expired batch. Concurrent requests for the same uncached entry must share one
load within a process; an instance limit alone does not serialize queries.

Scaling to zero discards the cache, so a cold start reloads all delivered
relations regardless of TTL. This is accepted; the cache is not a daily spend
limit. Deployment spend controls are specified in §13.4.

**Consistency scope.** A dashboard snapshot means one application load batch,
not a warehouse publication version. dbt replaces tables independently, so a
load during a build may mix versions. V1 accepts this limitation and performs
no cross-table analytical calculation or reconciliation. It does not promise
that a load comes from one completed, successful dbt build. Atomic publication
would require a separate warehouse design and is outside this dashboard scope.

The UI states analytical coverage from gold, not a last-refresh timestamp:

- Q1 visibly identifies the row marked `is_partial_year`.
- Q2 says "Snapshot through citation year {maximum loaded citation year}."
- Q3 snapshots and diagnostics say "Citations observed through {cohort +
  window}." A 2015 cohort at window 3 reads 2018, not 2025.
- Q3 trends and pooled comparisons state the fixed window and displayed cohort
  range. Each point's tooltip gives its own `cohort + window` bound.
- The Q3 heatmap gives per-cell bounds as specified in §8.4.

Gold has no source-extraction timestamp. Neither query time nor table
modification time is labelled analytical freshness. Methods explains that Q2
and Q3 require manual full-corpus refreshes; the current-year automation does
not keep those historical citation snapshots current.

### 4.4 Undefined metrics

Q3 permits valid rows with zero total citations. Their Ginis and top-k shares
are NULL; `age0_citation_share` is also NULL when ages 0..N contain no citations.
These are undefined ratios, not corruption or zero-valued metrics.

- Tables retain the row and display "Undefined — no citations" for the metric.
- Scatter plots omit a point with an undefined axis value and state how many
  points were omitted; those rows remain in the adjacent table.
- Trends leave a gap without connecting across an undefined value.
- Heatmaps distinguish an observable but undefined cell from a cell outside
  the observation triangle. Neither is coloured as a numeric zero.
- Colour domains use defined values only. If no defined values remain, show an
  explanatory empty visual and the table; do not invent a domain.

## 5. Overview page

The Overview is a compact reading path through the three results. Each delivered
question has one panel containing a miniature version of its primary visual, a
one-sentence finding, its relevant time bound, its load-bearing qualification,
and a link to the full page.

A qualification that must travel with a result travels with every rendering of
that result, including a miniature one. The Overview may compress the wording;
it may not drop the qualification and defer it to the linked page.

The final Overview contains:

### Q1 panel

- Strict and broad AI-share series from 1980 onward.
- A dashed or otherwise interrupted segment to the partial year.
- Finding: AI's share has risen from its trough; show the latest complete and
  partial-year values for each definition. Claim a record only when supported
  by the full loaded history under §3.
- Qualification: OpenAlex assigns topics retroactively, so the historical series
  shows how today's taxonomy classifies earlier work.

### Q2 panel

- A compact earliest-to-latest loaded citation-year comparison of median
  cited-work age for all three groups.
- Finding: display the change in each group's median age. State the five-year
  conclusion only while the loaded latest values support it.
- Qualification: citation-event-weighted ages, classified by the work receiving
  the citation, in a snapshot through the maximum loaded citation year. The
  year is derived from the loaded relation, never hardcoded.

### Q3 panel

- The 2020-cohort, five-year reach-versus-concentration scatter.
- Finding: AI and CV/PR pair relatively broad citation reach with highly
  concentrated winnings among the papers that are cited.
- Qualification: one cohort observed in calendar years 2021–2025, excluding
  publication-year citations. The latest citation year may still be settling.
  If the Q3 ceiling advances beyond 2025, that final qualification follows the
  new terminal cells rather than remaining attached to this fixed cell.

The Overview has no controls. It is a summary, not a second copy of the detailed
pages.

## 6. AI output page (Q1)

### 6.1 Primary visual

A directly labelled line chart plots share of CS works against publication year.
Strict and broad AI appear together by default. Complete years use solid lines;
the segment to the partial year is dashed and ends with a hollow marker.

The default range is 1980 through the latest loaded year. Earlier years are
available through an explicit full-history control. 1980 is the only pinned
bound; both ends of the full-history range come from the loaded relation.

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

Partial-year shares are provisional within-year ratios. They are not forecasts
of the complete year's share. For the reviewed data, both variants reach their
loaded-history maximum in partial 2026; only broad AI also sets a full-history
complete-year record in 2025.

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

The snapshot bound is displayed beside the title. Beside the visual, explain
that a work receiving 100 citations contributes 100 observations at its age;
this is a citation-event-weighted distribution. Age is the citation calendar
year minus the publication year, not an exact elapsed duration. Thresholds
include age 0: "≤5" means calendar ages 0–5.

Events are classified by the receiving work. The page does not claim to describe
what AI-authored papers cite or treat younger attention as proof of faster
intrinsic obsolescence. The Overview retains the weighting and cited-side
qualification in compressed form.

## 8. Citation concentration page (Q3)

Q3 contains separate internal views. Subfield and pooled-group results never
share a selector or dataframe.

Each view owns independent control state, except diagnostics explicitly reuse
the snapshot's cohort and window. Empty subfield selections show a prompt.
If the pinned default cohort/window is absent after a future warehouse change,
show that the reviewed default is unavailable; do not silently choose a new
headline population. Other published cells remain accessible on the full page.

### 8.1 Subfield snapshot

The default view is a scatter plot with:

- x-axis: `zero_share`, labelled "Share receiving no citations in years 1–N",
  with N replaced by the selected window;
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

Cohort is the controlling dimension. Every cohort published in gold is always
selectable; the window options are recomputed from the cells published for the
selected cohort. If the previously selected window is unavailable under the new
cohort, the control moves to the largest available window and displays a short
notice. The dependency never runs the other way: selecting a window never
removes a cohort from the cohort control. An unavailable cohort/window pair is
therefore unreachable, and is never queried or rendered as missing data.

The detail table shows subfield, papers, citations, uncited share, both Ginis,
and all three top-k shares for the selected cell.

Tooltips also include cohort, window, and the observation-end year. The metric
labels and denominators follow §8.6.

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

The adjacent table contains every displayed cohort/subfield row, its window,
observation-end year, paper and citation counts, and the selected metric.

### 8.3 Pooled comparison

The pooled comparison reads `gold_citation_gini_by_group` and is visually
separated from the two subfield views. It plots AI, CV/PR, and rest of CS across
publication cohorts at one fixed observation window.

Its controls are observation window and metric (the same options as cohort
trends); all three groups remain visible. The default is the five-year
all-paper Gini, which exposes the absence of a consistent AI excess.

The qualification is always visible: rest of CS pools heterogeneous subfields,
so its Gini contains between-subfield inequality that no individual subfield
carries. This view and the subfield views are two relations at different grains.
Its table and tooltips expose the same fields as cohort trends, keyed by group.

### 8.4 Lifecycle heatmap

The heatmap plots the complete observable triangle for one selected subfield:

- rows: publication cohort;
- columns: cumulative complete years after publication;
- cell colour: selected metric; and
- cell tooltip: cohort, observation window, the citation year the cell is
  observed through, paper count, citation count, and metric value at §10's
  display precision.

<!-- prettier-ignore -->
| Control | Options | Default |
|---|---|---|
| Subfield | Classified CS subfields | Artificial Intelligence |
| Metric | Uncited share, Cited-only Gini, All-paper Gini, Top 1%, Top 5%, Top 10% | Cited-only Gini |

Cells outside the observable triangle remain blank and are labelled in the
legend as "not yet observable". Observable cells with undefined metrics use a
distinct neutral mark and legend entry under §4.4. Switching subfield does not
rescale colours to that subfield alone. The colour domain is
the observed global min-to-max range for the selected metric across classified
subfields, making the selected heatmaps comparable.

The text states that every window is cumulative ages 1..N and that terminal
cells may still be settling. Because the heatmap shows the whole triangle at
once rather than one selected cell, its observation bound is the diagonal
itself: each cell is observed through `cohort + window`, and the terminal
diagonal ends at the Q3 window ceiling. The tooltip therefore carries the
per-cell bound, and no single global "observed through" year is displayed over
the grid.

The adjacent table exposes the observable rows for the selected subfield,
including undefined metrics, with the same fields as the tooltips.

### 8.5 Age-0 diagnostics

Age 0 is not a global inclusion toggle because gold does not publish every
headline metric under an including-age-0 definition. An expandable diagnostic
section below the subfield snapshot has its own subfield selector (default AI)
and reuses that snapshot's cohort/window controls. It shows:

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

"Uncited" means no citations in ages 1..N, even if a paper received citations
in its publication year. Top-k labels say "Citation share received by the top
k% of all cohort papers"; the count is `ceil(k / 100 * n_papers)`, including
uncited papers in the population. These are shares of window citations, not
percentages of cited papers. Ginis range from 0 toward 1 as inequality rises.

Calendar years 1..N are equal-duration windows starting the January after
publication, not each paper's first N years of life. Every Q3 rendering carries
the age-0 exclusion. Views containing cells ending at the loaded Q3 ceiling
(maximum `publication_year + citation_age`) also carry a settling caveat.
These qualifications ship with the first affected view, including Overview and
pooled comparisons in Waypoint 3.

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
- the negative-age exclusion: upstream citation years before publication are
  excluded from Q2 and Q3; gold does not publish their excluded weight, so the
  app does not present a fixed historical percentage as a current measurement;
- the current bounds derived from loaded gold; and
- a link back to the repository's full findings and design rationale.

It does not reproduce reconciliation baselines or internal test counts. Those
remain in `FINDINGS.md`.

## 10. Visual and interaction contract

- Use one stable palette across pages: AI, CV/PR, rest of CS, and neutral
  subfields keep the same identities.
- Pair colour with direct labels, line styles, or point shapes. Colour alone
  never carries identity.
- Use integer formatting for counts and calendar ages, one decimal place for
  percentages, and three decimals for Ginis in chart labels, prose, and tooltips.
- Chart titles state the population and time/window scope.
- Tables preserve the underlying numeric values and allow inspection beyond
  rounded display precision. Tooltips report observed point values at the
  stated display precision; they do not claim full numeric precision.
- Every primary visual has an adjacent table representing the active state.
- Controls use presentation names, never raw column names or URL-form subfield
  ids.
- Shortened subfield labels are an application-owned mapping keyed on
  `subfield_id`, not a substring of `subfield_display_name`. "Computer Graphics"
  is the application's short form of the published "Computer Graphics and
  Computer-Aided Design". An id with no short form falls back to its full
  published display name, so a new subfield renders correctly rather than
  disappearing.
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
  snapshot.py         the dashboard snapshot type and its accessors
  exceptions.py       typed dashboard-data exceptions
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

There is no `models.py`: in this repository "model" means a dbt model, and the
established package convention is a dedicated `exceptions.py`.

Public functions receive their data or BigQuery client explicitly. Importing a
page module performs no query. Streamlit owns caching at the application edge;
the data loader itself remains callable and testable without Streamlit or a
network.

Chart constructors return declarative chart objects from supplied in-memory
data. They do not query, cache, read environment variables, or mutate session
state.

### 11.1 Dependencies

The proposed `dashboard` dependency group declares `streamlit`, `altair`,
`google-cloud-bigquery[pandas]`, and `pandas`. Streamlit and Altair are new to
the lockfile; BigQuery, pandas, and pyarrow already arrive through dbt.
Dependencies still require explicit approval before editing `pyproject.toml`.

### 11.2 Image scope

The image installs only the locked `dashboard` group and dashboard source.
It must not contain Polars, Dagster, dbt, DuckDB, or the GCS client. Do not
install the base project dependencies. Direct dashboard imports are declared in
the group; required transitive packages come from its locked dependency tree.

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
- Container: 1 vCPU, 1 GiB memory, port 8080.
- Container concurrency: 8. Request timeout: 120 s. Both are pinned rather than
  inherited from Cloud Run defaults.
- The service receives `OPENALEX_GCP_PROJECT`; the production dataset remains
  pinned in code.
- The container runs Streamlit headlessly on `0.0.0.0:8080`.
- No secrets, service-account keys, volumes, or writable persistent storage are
  mounted.

Memory starts at 1 GiB; adjust only from measured startup and concurrent-session
usage. No baseline memory measurement is claimed by this spec.

The browser receives no Google credentials. Cloud Run supplies Application
Default Credentials to the server process through the attached runtime service
account.

**Accepted availability risk.** This public portfolio service has no rate
limiting or Cloud Armor policy. A client can saturate it. The instance cap limits
configured scale; it does not establish a daily spending limit.

Streamlit holds a websocket for each open browser tab, and Cloud Run bills CPU
while a request is in flight, so billed instance-time tracks how long tabs stay
open rather than how much computation occurs. The 120 s request timeout forces a
reconnect, not a billing pause. §13.4 states the resulting worst case.

### 13.2 Runtime identity

Terraform creates a dedicated `dashboard-runner` service account with exactly:

- `roles/bigquery.jobUser` on the project; and
- `roles/bigquery.dataViewer` on each delivered production gold table, using
  table-scoped grants rather than a dataset-wide grant.

The production analytics dataset also contains staging and silver; the runtime
identity receives no read grant on those tables. It receives no editor, dev,
raw, or GCS grant and never reuses the dbt runner identity. Deployment checks
must verify that gold remains readable after dbt replaces its tables.

### 13.3 Image and deployment

Terraform owns an Artifact Registry repository and the Cloud Run service. The
image is built from a repository Dockerfile, tagged with the git commit SHA,
and pushed explicitly. Terraform deploys its content digest so the revision
identifies an immutable image.

The Dockerfile uses committed `uv.lock`, copies the dashboard subtree and parent
package `__init__`, and runs as a non-root user. Its installed packages must
satisfy §11.2.

Enabling `run.googleapis.com` and `artifactregistry.googleapis.com` precedes any
apply; neither is enabled on the project today. The initial Artifact Registry
bootstrap precedes the first image push; the Cloud Run resource is applied only
after that image exists. Subsequent waypoint deployments reuse the same public
service URL and advance only its immutable image reference. Continuous
deployment is deliberately deferred: a reviewed waypoint is promoted by an
explicit build, push, plan, and apply.

### 13.4 Spend guards

The design distinguishes per-job limits, configured compute scale, and
cumulative spend. Fixed 100 MiB query limits and maximum instances 1 are pinned.
Neither serializes all queries nor provides a daily spending ceiling;
concurrency is 8 and cold starts discard the cache.

**Resolved.** GCP publishes no per-service-account daily bytes quota: the
`bigquery.googleapis.com/quota/query/usage` metric exposes only a project
bucket and a per-principal bucket, and carries no principal dimension. The
per-principal bucket is used instead, so the dashboard cannot consume the
pipeline's allowance and no second project is needed. Measurements, rejected
alternatives, and the commands that produced them are in
`docs/dashboard-spend-guards.md`.

<!-- prettier-ignore -->
| Guard | Pinned setting |
|---|---|
| Per-job limit | `maximum_bytes_billed` 100 MiB (§4.2) |
| Daily query quota | metric `bigquery.googleapis.com/quota/query/usage`, limit `1/d/{project}/{user}`, override value `262144`, unit **MiB** — 256 GiB per identity per day |
| Quota resource | `google_service_usage_consumer_quota_override` |
| Exhaustion behavior | query jobs fail with `quotaExceeded`; no silent degradation and no partial results |
| Budget | €10 per calendar month, scoped to the project, Terraform `google_billing_budget` |
| Budget alerts | 50%, 90% and 100% of actual spend plus 100% of forecast, by email to the owner |
| Kill switch | manual `gcloud run services update openalex-dashboard --max-instances=0` |

The quota value sits about 5.3× above the largest measured pipeline day. If a
future full-corpus refresh trips it, dbt fails loudly and the value is a
one-line change; that is the intended failure mode, not a regression. The
override unit is MiB, not bytes — a byte count is 2^20 too large and silently
ineffective.

**What remains unbounded.** The dashboard's own query exposure is about 40 MB
per cold snapshot load: four relations at BigQuery's 10 MB per-table minimum,
against 197 KiB of actual gold. The larger exposure is Cloud Run, on the order
of $90–100 per month if one instance is held active continuously (§13.1).
Maximum instances 1 bounds that rate; nothing bounds the total. Budget alerts
notify; they do not stop spending or guarantee a notification within a day. No
hard total-cost bound is promised, and the kill switch above is the response.

**Prerequisites.** Before the first apply the Terraform runner needs
`roles/serviceusage.quotaAdmin` on the project and `roles/billing.costsManager`
on the billing account, and `billingbudgets.googleapis.com` must be enabled;
none of the three is in place today. Apply the quota override and read its
effective limit back before the first deployment. If the API refuses the
override, return that tradeoff for review rather than substituting a
project-wide cap.

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
- data-derived numerical claims, full-history Q1 record checks, and descriptive
  titles for non-default Q3 selections;
- Q2 group and threshold mappings;
- Q3 cohort/window validity, including that changing cohort never leaves an
  unavailable window selected and that changing window never removes a cohort;
- the Q3 observation bound derived from the active selection, asserted on a
  non-default cohort/window pair so a hardcoded relation maximum fails;
- equal-window trend filtering;
- the subfield short-label mapping, including fallback to the published display
  name for an unmapped id;
- exclusion of `__unclassified__` from analytical views;
- separation of subfield and pooled data paths;
- blank, not zero, heatmap cells outside the observable triangle;
- distinct undefined-metric rendering, trend gaps, and all-undefined selections;
- age-0 diagnostics without a false global inclusion toggle;
- independent Q3 view state and diagnostics' shared snapshot cohort/window;
- tables representing all displayed rows in each Q3 view;
- one cache load per concurrent miss, complete-batch caching, and no expired
  result after a failed refresh;
- the presence of each required qualification on both the Overview panel and the
  full page for every delivered question;
- that no dashboard module imports Polars, Dagster, dbt, DuckDB, or the GCS
  client, so the §11.2 image scope is enforced in the test suite and not only at
  build time; and
- Streamlit page smoke tests using committed fixtures.

Fixtures under `tests/dashboard/fixtures/` include one small production CSV
extract per relation with enforced column names. Separate, explicitly synthetic
fixtures cover valid cases absent from production: all-zero citation cells,
age-0-only citations, the unclassified bucket, and an unmapped subfield id.
Include partial years, shorter-than-default windows, missing pinned defaults,
and refreshed values that invalidate old narrative claims. Record each extract's
query date and analytical bounds so it is not confused with a live baseline.

Every waypoint runs at least:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
terraform fmt -check -recursive terraform
terraform -chdir=terraform validate
```

Validation needs installed providers/modules, not access to remote state.
Initialize a fresh validation working directory with
`terraform -chdir=terraform init -backend=false`. Formatting and validation can
run in CI without cloud credentials; deployment plans remain explicit checks.

The container image must build locally, and its installed package list is
checked against §11.2: Polars, Dagster, dbt, DuckDB, and the GCS client must be
absent.

The §13.4 quota override and budget are cloud-side facts with no automated
test: before the first deployment, confirm the override reads back its
effective limit and that the budget exists.

After deployment, a smoke check confirms that the public service returns
successfully and that each delivered page loads from production gold.

## 15. Delivery waypoints and review gates

Implementation starts only after the user approves dependencies and gives the
signal; §13.4 is resolved. Each subsequent waypoint needs explicit
authorization after review of the preceding deployment. Shared exit checks are
§14's local verification, image inspection, and public smoke checks; repeat
them at every waypoint. Deployments use the same URL and an immutable image
digest.

### Waypoint 1 — Q1 vertical slice

Deliver the approved dependency group, shell, Q1 loader/cache, fixtures and tests,
Q1-only Overview, complete Q1 page, and initial Methods page. Add the scoped
image, Artifact Registry, gold-only runtime IAM, Cloud Run service, reviewed
spend controls, and explicit build/push/plan/apply commands.

Accept when the Terraform plan contains only reviewed dashboard infrastructure,
the public service reads Q1 gold, complete/partial-year claims are correct, and
taxonomy and partial-year qualifications appear on both renderings. The user
reviews the deployment before authorizing Q2.

### Waypoint 2 — Q2

Deliver Q2's data path, fixtures, tests, Overview panel, both measures, controls,
quantile context, table, and qualifications.

Accept when values reconcile with findings under matching bounds and every
measure/threshold/group/detail-year interaction works. Citation weighting,
cited-side classification, and snapshot coverage must be visible. The user
reviews the deployment before authorizing Q3.

### Waypoint 3 — Q3 core

Deliver separate subfield and pooled data paths, fixtures and tests, Q3 Overview,
snapshot, equal-window trends, pooled comparison, valid controls, tables, and
undefined-metric behavior. Include age-0, terminal-settling, and pooled-grain
qualifications with the affected visuals now.

Accept when the default 2020/five-year cell reconciles with findings, invalid
cohort/window pairs are unreachable, and bounds track a non-default selection.
The pooled and subfield paths stay separate, and claims distinguish cited-only
from all-paper concentration. The user reviews before authorizing the final
waypoint.

### Waypoint 4 — Q3 full and final integration

Deliver the heatmap, age-0 diagnostics, completed Methods page, final
accessibility/mobile/theme review, and README link to the service.

Accept when heatmap values and global colour domains match gold; unavailable,
undefined, and zero cells are distinguishable; diagnostics follow their stated
controls; and both themes and narrow/wide layouts have been visually reviewed.
The user accepts the completed deployment.
