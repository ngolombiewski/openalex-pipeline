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
Credentials — the developer's own ADC identity directly, with no impersonation.
Unlike dbt and Terraform, the dashboard never impersonates a service account
locally, and it never runs locally as `dashboard-runner`. Automated tests use committed fixtures and make no network or cloud
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

One cache miss performs the four fixed BigQuery jobs. A failed refresh remains a
failure; the application does not silently substitute an expired snapshot.

The TTL is not the main thing bounding warehouse jobs, and the spec should not
pretend otherwise. With minimum instances 0, Cloud Run scales to zero on idle
and the process-local cache dies with the container, so on a low-traffic public
service most first visits pay a cold start plus four fresh queries regardless of
TTL. The real bound is that the queries are fixed, tiny, and capped: the four
gold relations total a few thousand rows, and `maximum_bytes_billed` caps each
job. Capping instances at one additionally prevents concurrent traffic from
multiplying those jobs across processes. Cold-start refreshes are accepted, not
engineered away; raising minimum instances to 1 would trade continuous cost for
latency the audience does not need.

The UI describes freshness through the bounds present in gold:

- Q1 visibly identifies the row marked `is_partial_year`.
- Q2 says "Snapshot through citation year {maximum loaded citation year}."
- Q3 states the bound implied by the **active selection**, not the relation
  maximum: "Citations observed through {selected cohort + selected window}." A
  2015 cohort at a three-year window reads 2018, not 2025.

It does not label BigQuery table modification time as analytical freshness.

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
- Finding: AI's share of CS output is at an all-time high after a long decline
  and renewed rise.
- Qualification: OpenAlex assigns topics retroactively, so the historical series
  shows how today's taxonomy classifies earlier work.

### Q2 panel

- A compact 2012-to-latest comparison of median cited-work age for all three
  groups.
- Finding: by the latest citation year, median citation attention in every group
  had moved to work no more than five years old.
- Qualification: a snapshot through the maximum loaded citation year, classified
  by the work receiving the citation. The year is derived from the loaded
  relation, never hardcoded.

### Q3 panel

- The 2020-cohort, five-year reach-versus-concentration scatter used in the
  README.
- Finding: AI and CV/PR pair relatively broad citation reach with highly
  concentrated winnings among the papers that are cited.
- Qualification: one publication cohort observed over five complete
  post-publication years, excluding the publication year itself.

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

Cohort is the controlling dimension. Every cohort published in gold is always
selectable; the window options are recomputed from the cells published for the
selected cohort. If the previously selected window is unavailable under the new
cohort, the control moves to the largest available window and displays a short
notice. The dependency never runs the other way: selecting a window never
removes a cohort from the cohort control. An unavailable cohort/window pair is
therefore unreachable, and is never queried or rendered as missing data.

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
- cell tooltip: cohort, observation window, the citation year the cell is
  observed through, paper count, citation count, and exact metric value.

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

The text states that every window is cumulative ages 1..N and that terminal
cells may still be settling. Because the heatmap shows the whole triangle at
once rather than one selected cell, its observation bound is the diagonal
itself: each cell is observed through `cohort + window`, and the terminal
diagonal ends at the Q3 window ceiling. The tooltip therefore carries the
per-cell bound, and no single global "observed through" year is displayed over
the grid.

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
- the negative-age exclusion: a small share of upstream records carry citation
  years before their own publication year, they are excluded from both Q2 and
  Q3 by contract, and the excluded weight is roughly one percent;
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

The runtime needs Streamlit, Altair, the BigQuery Python client, and pandas.
Only one of those is genuinely new to the environment:

<!-- prettier-ignore -->
| Package | Current status | Ask |
|---|---|---|
| `streamlit` | absent | **new top-level dependency** |
| `altair` | absent | arrives with Streamlit; declare it directly because charts import it |
| `google-cloud-bigquery` | already resolved in `uv.lock` via `dbt-bigquery`, with the `pandas` extra | promote transitive → direct, declared as `google-cloud-bigquery[pandas]` |
| `pandas`, `pyarrow` | already resolved in `uv.lock` via the same path | none directly; they enter the `dashboard` group through the `pandas` extra above |

So the approval decision is about adding Streamlit, plus making two existing
transitive packages explicit. That is a smaller change than "three new
dependencies," and it is worth deciding on the accurate version.

They still require explicit approval before implementation. Nothing is added to
`pyproject.toml` until that approval is given.

### 11.2 Dependency group and image scope

The dashboard's packages go in a dedicated `dashboard` dependency group, not
into the base `[project.dependencies]`. The container image installs **only**
that group plus the `openalex_pipeline.dashboard` package. The group is
self-contained: everything the dashboard process imports at runtime is declared
in it or reachable through one of its extras, because nothing from
`[project.dependencies]` is present in the image.

This is load-bearing rather than tidiness. The base dependency set carries
Dagster, the Dagster webserver, dbt-core, dbt-bigquery, DuckDB, and the GCS
client — hundreds of megabytes, none of it reachable from a dashboard process.
Installing the project wholesale would ship the entire orchestration and
warehouse toolchain into a public container to render four small tables. The
image must not contain Dagster, dbt, DuckDB, or the GCS client, and a build that
does is a failed build, not a large one.

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

Memory is 1 GiB because Streamlit, pandas, and pyarrow are all resident at once;
512 MiB leaves no headroom above their baseline. If a measured cold start shows
otherwise, dropping to 512 MiB is a later, evidence-backed change.

The browser receives no Google credentials. Cloud Run supplies Application
Default Credentials to the server process through the attached runtime service
account.

**Accepted availability risk.** The service is public, unauthenticated, capped
at one instance, and has no rate limiting or Cloud Armor policy. A single client
can therefore saturate it. This is accepted: the dashboard is a portfolio
artifact, an outage is not an incident, and the alternative is infrastructure
the audience does not justify. The risk is bounded by §13.4, which caps what a
saturating client can cost rather than preventing the saturation.

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

The Dockerfile installs the `dashboard` dependency group only, from the
committed `uv.lock` so the image resolves to the same versions the test suite
ran against. It copies `src/openalex_pipeline/dashboard/` and its package
`__init__`, not the whole source tree, and it runs as a non-root user. A build
that pulls Dagster, dbt, DuckDB, or the GCS client into the image has violated
§11.2 and must be fixed rather than shipped.

The initial Artifact Registry bootstrap precedes the first image push; the Cloud
Run resource is applied only after that image exists. Subsequent waypoint
deployments reuse the same public service URL and advance only its immutable
image reference. Continuous deployment is deliberately deferred: a reviewed
waypoint is promoted by an explicit build, push, plan, and apply.

### 13.4 Spend guards

This is the first surface in the project where cumulative cost is influenced by
an anonymous third party, so the per-job circuit breaker the warehouse relies on
is not sufficient on its own. `maximum_bytes_billed` caps one query; it says
nothing about how many queries a visitor can trigger. Terraform therefore owns
three layers:

<!-- prettier-ignore -->
| Guard | Value | Bounds |
|---|---|---|
| `maximum_bytes_billed` per dashboard query | 100 MiB | cost of any single query |
| Cloud Run maximum instances | 1 | concurrent compute, and concurrent query fan-out |
| BigQuery custom quota on the dashboard service account | daily bytes-billed ceiling | total warehouse spend a visitor can drive in a day |

A project-level budget alert covers what the quota does not: it notifies rather
than blocks, and it exists so an unexpected pattern is noticed within a day
instead of at the end of the month. The quota is set on the `dashboard-runner`
service account specifically, so exhausting it takes the dashboard down without
touching dbt, Dagster, or any pipeline job.

Blast radius if the dashboard is scraped continuously: the queries are fixed and
small, the instance cap serializes them, and the daily quota terminates them.
The failure mode is an unavailable dashboard, not an unbounded bill.

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
- age-0 diagnostics without a false global inclusion toggle;
- the presence of each required qualification on both the Overview panel and the
  full page for every delivered question;
- that no dashboard module imports Polars, Dagster, dbt, DuckDB, or the GCS
  client, so the §11.2 image scope is enforced in the test suite and not only at
  build time; and
- Streamlit page smoke tests using committed fixtures.

Fixtures are committed CSV extracts of the production gold relations under
`tests/dashboard/fixtures/`, one file per relation, small enough to read in a
diff. They carry the enforced column names and a representative slice of rows,
including the partial year, an unmapped subfield id, and a cohort whose window
options are shorter than the default.

Every waypoint runs at least:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
terraform fmt -check -recursive terraform
terraform validate
```

The two Terraform commands are local checks: `validate` needs an initialized
backend, so it stays out of CI for the same reason the existing pipeline
infrastructure does.

The container image must build locally, and its installed package list is
checked against §11.2: Dagster, dbt, DuckDB, and the GCS client must be absent.
After deployment, a smoke check confirms that the public service returns
successfully and that each delivered page loads from production gold.

## 15. Delivery waypoints and review gates

No waypoint begins until the previous deployed waypoint has been tested and the
user explicitly authorizes continuation.

### Waypoint 1 — Q1 vertical slice

Deliver:

- approved dependencies, the `dashboard` dependency group, and pinned
  application contracts;
- application shell and delivered-page-only navigation;
- Q1 production-gold loader, cache, fixtures, and tests;
- Overview containing only the Q1 panel, carrying its qualification;
- complete Q1 page and initial Methods & data page;
- Docker image built to the §11.2 scope;
- Artifact Registry, dashboard identity/IAM, public Cloud Run service, and the
  §13.4 spend guards; and
- documented explicit deployment commands.

Exit criteria:

- all local checks and container build pass;
- the image contains no Dagster, dbt, DuckDB, or GCS client;
- Terraform plan contains only the reviewed dashboard infrastructure, including
  the BigQuery custom quota and budget alert;
- the public URL loads Q1 from production gold;
- partial-year and taxonomy qualifications are visible on both the Overview
  panel and the Q1 page; and
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
- the displayed observation bound tracks the selected cohort and window, checked
  on a non-default pair;
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
