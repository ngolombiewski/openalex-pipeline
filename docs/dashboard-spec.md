# Dashboard specification

> **Status: draft for review, 2026-09-20.** The architecture is agreed. This
> document specifies the first version; it does not authorize implementation
> or publication.

## 1. Purpose

The dashboard is the visible analytical outcome of the portfolio: a short,
well-designed visual essay about AI within computer-science research. Its
primary reader is a recruiter or hiring manager spending a minute or two with
the project. A technical reader can inspect values and methods without leaving
the site.

Success means the reader understands the three findings without operating any
controls, sees the qualifications that make them defensible, and can reach the
repository to inspect the engineering behind them. Fast first load, readable
charts, and deliberate typography take priority over exploratory features.

## 2. Architecture and scope

```text
Production gold marts
  → explicit, reviewed export
  → committed JSON snapshot + provenance
  → Astro static build with Observable Plot charts
  → GitHub Pages
```

The dashboard is an independent project under `dashboard/` in this repository.
It uses Astro, TypeScript, ordinary CSS, and Observable Plot. Node.js and npm
are development/build tools. The deployed result is HTML, CSS, JavaScript, and
static assets; there is no application server or custom API.

Local development, tests, builds, and publication consume committed files and
need no GCP credentials or running pipeline. Optional chart interactions run
in the browser. Data and narrative change only through a reviewed release.

The first version includes one reading page, three primary charts, exact-value
tables, methods, snapshot provenance, and a repository link. It has no live
queries, refresh timers, authentication, saved state, analytics, server-side
functions, containers, dashboard Terraform, or dashboard-specific spend guards.
There is no React dependency, CSS framework, or browser database engine.

## 3. Reading experience

The page proceeds through:

1. A concise introduction: what was studied, why these questions matter, and
   that the results are a frozen snapshot.
2. AI's share of CS output, with both definitions visible.
3. The age of work receiving citation attention, comparing three groups.
4. Citation reach and concentration across CS subfields.
5. Methods and data, with provenance and a repository link.

Use anchor links for navigation. Each analytical section has a finding-led
heading, a short interpretation, one chart, a nearby qualification, and an
expandable exact-value table. Methods and tables may be collapsed; essential
qualifications remain visible. There is no separate Overview duplicating the
charts, sidebar of analytical pages, or global year control.

The initial view is the complete intended story. Hover/tap details and opening
tables add information without changing the analytical population. The first
version has no measure, group, year, cohort, or observation-window selectors.

## 4. Frozen data contract

### Snapshot contents

Commit one full export per production gold relation under `dashboard/data/`,
using the relation name as the JSON filename. Export the enforced gold columns
with their original names; do not round or recompute analytical measures.

<!-- prettier-ignore -->
| Relation | Grain | Role in this release |
|---|---|---|
| `gold_ai_share_by_year` | publication year × variant | Q1 series and full-history checks |
| `gold_citation_age_by_year` | citation year × cited group | Q2 series and supporting values |
| `gold_citation_gini_by_subfield` | subfield × publication cohort × citation age | Q3 fixed cohort/window |
| `gold_citation_gini_by_group` | cited group × publication cohort × citation age | Preserved evidence; no pooled chart in this version |

Each file is an array of row objects ordered by its grain keys. JSON preserves
booleans, strings, numbers, and explicit nulls. Integer serialization must be
lossless within JavaScript's safe integer range; reject an export that cannot
meet that contract. Column names and TypeScript row types are explicit, with
nullability matching gold. Type assertions alone do not validate imported data.

The source dataset is production `openalex_analytics`. The reduced dev slice
is not an input: in particular, it omits older cited works needed by Q2.
The dashboard does not read staging, silver, raw data, or extraction state.

### Exporter

A single script, `tools/export_dashboard_snapshot.py`, produces the snapshot.
It is run manually with `uv run` and belongs to the Python project, not to
`dashboard/`. It reads production gold and writes `dashboard/data/`; it never
runs dbt or writes to the warehouse.

- **Client and credentials.** Use `google-cloud-bigquery`, an explicit
  dependency in `pyproject.toml`. Impersonate the dbt service account named
  by an environment variable documented in `.env.example`. Set
  `maximum_bytes_billed` on every query.
- **Queries.** One hard-coded query per relation:
  `SELECT <enforced columns> FROM openalex_analytics.<relation> ORDER BY <grain keys>`.
  The column lists are explicit in the script. Raise if the returned columns
  differ from them.
- **Types.** Typed client rows serialize to JSON numbers, booleans, strings,
  and nulls. Raise if an integer falls outside JavaScript's safe range.
- **Overlap detection.** Read every relation's last-modified time before and
  after the queries. If any changed, raise and write nothing.
- **Bounds.** Read the bound variables from `dbt_project.yml` and check that
  the exported data agrees with them: publication-year range, partial-year
  flag, Q2 citation years, and Q3 cohort floor and citation-year ceiling.
  Raise on any mismatch; record the confirmed values in `snapshot.json`.
- **Pipeline revision.** A required `--pipeline-revision` argument that also
  accepts the literal `unknown`. The script never substitutes its own commit.
- **Writes.** Write all five files to a temporary directory beside
  `dashboard/data/`, then replace it with one rename. A partial snapshot is
  never in place.
- **Errors.** Known failures raise `ExportError` naming the relation and the
  problem. Unknown errors propagate.

Pytest covers the script with a fake client: column mismatch, the safe-integer
limit, a modification time changing during export, and a bounds mismatch.

### Provenance and publication boundary

A small `snapshot.json` records:

- export time in UTC and fully qualified source table names;
- the pipeline code revision associated with the reviewed results, explicitly
  recording an unknown revision rather than substituting the exporter revision;
- corpus publication bounds and the partial publication year;
- Q2 citation-year bounds and Q3 cohort floor and citation-year ceiling; and
- exported row counts for each relation.

The initial intended analytical bounds are publication years 1950–2026, with
2026 partial; Q2 citation years 2012–2025; and Q3 cohorts from 2012 with citations
through 2025. Confirm these against the exported results before publication.
Do not stamp a new export with an old measurement's date.

Export all four relations from a reviewed warehouse state with no warehouse
build running during the export. If a build overlaps, discard the candidate
export and repeat after completion. This is a manual publication precondition,
not a new orchestration or warehouse versioning system. Review the files,
provenance, and narrative together and commit them as one publication input.

Export time is not source freshness. The page displays analytical coverage
beside each result; Methods labels the export date separately. Q2 and Q3 are
historical citation snapshots and are not kept current by the pipeline's
current-year refresh. The frozen export preserves published aggregates, not
the underlying source records required to rebuild them.

### Loading and failure behavior

The build checks the file boundary: required files, row shapes/types, nonempty
relations, recorded bounds/counts, and the rows needed by the fixed views.
Known snapshot errors raise `SnapshotDataError`, identify the file and problem,
and fail the build. Unknown errors propagate. There is no warehouse fallback
or substituted dataset.

Trust gold's analytical invariants; do not duplicate dbt's statistical tests.
Filtering, display formatting, and selecting chart columns belong here;
recalculating medians, Ginis, or pooled results does not.

Q3 null ratios (Ginis and top-k shares) mean undefined, not zero. Retain those rows in the table with an
explanation; omit an undefined scatter point and state the omission count. If
the snapshot cannot support the intended headline, stop the release for content
review rather than generating a replacement story automatically.

## 5. The three analytical sections

### Q1 — AI's share of CS output

Render a directly labelled line chart from 1980 through the snapshot's latest
publication year, showing strict and broad AI together. Plot `share`; retain
`ai_works`, `cs_works`, year, variant, and partial status in the detail table.
Use a dashed final segment and hollow marker for the partial year, labelled
with its actual year. The table covers the same displayed years and variants.

Strict AI is subfield 1702; broad AI also includes computer vision and pattern
recognition, subfield 1707. Explain these names next to the chart.

The intended finding is the rise from the mid-2010s trough. The reviewed
baseline has strict/broad shares of 35.0%/49.7% in 2025 and 39.8%/54.7% in
partial 2026. Check these against the release snapshot. Any record claim must
use the full exported history and distinguish complete from partial years:
strict AI's 2025 share is below its 1951 share, outside the chart's range.

Visible qualification: OpenAlex applies a modern taxonomy retroactively, so
the historical line describes how today's taxonomy classifies earlier work.
Partial-year shares are provisional within-year ratios, not forecasts.

### Q2 — Citation attention has shifted toward younger work

Render a directly labelled line chart of `median_citation_age` by
`citation_year`, with AI, CV/PR, and rest of CS all visible. Preserve annual
observations without smoothing. The intended baseline is 2012–2025: medians
move from 8 to 5 years for AI, and 7 to 5 for the other two groups.

Show the latest year's `share_age_lte_5` as compact supporting values, not a
second interactive chart. The reviewed baseline is 55.4% for AI, 57.2% for
CV/PR, and 54.3% for rest of CS. The exact-value table includes every displayed
year/group, citation events, cited works, the three age quantiles, and the
shares aged at most 2, 5, and 10 years.

Visible qualification: these are citation-event-weighted ages, grouped by the
work receiving the citation. A work cited 100 times contributes 100 age
observations. This does not establish what AI-authored papers cite or prove
faster intrinsic obsolescence. Label the snapshot through citation year 2025
for the intended release. Ages are calendar-year differences; “at most five”
includes ages 0–5.

### Q3 — Broad citation reach can coexist with concentrated rewards

Render one scatter plot for the 2020 publication cohort with five complete
post-publication calendar years, 2021–2025. In gold this is the cell
`publication_year = 2020, citation_age = 5`; `citation_age = N` is the
cumulative window of ages 1 through N, so age-0 diagnostics are outside it.

- x-axis: `zero_share`, labelled “Share with no citations in years 1–5”;
- y-axis: `gini_cited_only`, labelled “Gini among cited papers”;
- one point per classified CS subfield, excluding `__unclassified__`;
- highlight AI and CV/PR with labels and shapes as well as colour; and
- also directly label Computer Graphics and Information Systems.

Use subfield IDs for identity. Chart annotations use this explicit mapping;
an unmapped ID retains its published display name. The detail table always
shows the published display name.

<!-- prettier-ignore -->
| Subfield ID | Published display name | Chart label |
|---|---|---|
| 1702 | Artificial Intelligence | AI |
| 1707 | Computer Vision and Pattern Recognition | Computer Vision & PR |
| 1704 | Computer Graphics and Computer-Aided Design | Computer Graphics & CAD |
| 1710 | Information Systems | Information Systems |

Explain that Gini increases toward 1 as citations become more unequal.

The intended finding is that AI and CV/PR combine relatively broad citation
reach with high concentration among papers receiving citations. In the
reviewed cell, AI's uncited share is 46.4% and cited-only Gini is 0.760; CV/PR's
are 35.3% and 0.751. Computer Graphics has a similar cited-only Gini to AI but
a substantially larger uncited share. Check claims against unrounded values.

The table includes every classified subfield in this cell, paper and citation
counts, uncited share, both Ginis, and top-1%, top-5%, and top-10% citation
shares. For each subfield/cohort/window, top-k selects the
`ceil(k × n_papers)` most-cited papers, using all cohort papers (including
uncited ones) to set the cutoff. Its share is their window citations divided
by the subfield/cohort's total window citations. The result does not depend
on tie order. A share is null when total window citations are zero. The page
states this plainly, e.g. “Top 10% share: the citations received by the
most-cited tenth of all papers in the cohort, uncited papers included, as a
share of all citations.”
Explain that all-paper Gini also reflects the uncited share. Do not describe
AI as the most concentrated subfield on the all-paper measure, or present a
subfield comparison as a pooled AI-versus-rest result.

Visible qualification: publication-year citations are excluded; “uncited”
means no citations during calendar years 2021–2025, not never cited. These
are five equal calendar years starting after publication, not each paper's
first five years of life. The terminal citation year may still be settling.

Cohort trends, pooled comparisons, lifecycle heatmaps, metric switching, and
age-0 diagnostic controls are deferred. Preserving their source columns in the
snapshot does not create a requirement to expose them in the UI.

## 6. Methods and visual design

Methods explains the CS corpus, classification definitions, the three meanings
of year, citation weighting, Q3's observation window and denominators, and the
exclusion of invalid negative citation ages. Explain that pooled Ginis cannot
be obtained by averaging subfield Ginis. Include snapshot provenance and a
repository link for deeper inspection. Internal test counts, operational
configuration, and historical reconciliation tables do not belong in the page.

Use consistent colours for AI, CV/PR, and rest of CS; use neutral colours for
other subfields. Q1's broad AI includes CV/PR and must be labelled as a combined
definition, not assigned CV/PR's identity. Pair colour with labels, line styles,
or shapes. Use one intentionally designed light theme for the first release.

Typography, spacing, and annotation placement should support the reading order.
Use integer counts and ages, one decimal place for percentages, and three
decimals for Ginis in charts and prose. Preserve additional stored precision
in detail tables. Numerical text comes from snapshot values where practical;
interpretation is authored and reviewed with that snapshot.

At mobile widths the page is a single column, labels remain readable, and
there is no page-level horizontal overflow. Wide tables may scroll in their
own containers. Use semantic headings, chart descriptions, visible focus,
keyboard-operable disclosures, and adequate contrast. No essential information
is available only on hover; tables provide exact values for touch and keyboard
users. Respect reduced-motion preferences and avoid decorative animation.

## 7. Build and tooling

The project owns `dashboard/package.json`, `package-lock.json`, source,
snapshot data, and tests. Dependencies are local to `dashboard/node_modules/`.
Keep the Python environment and dependency files independent. Use the existing
Node/npm installation; no global Astro installation or version manager is
required. Pin the tested Node version for CI and record it in project metadata.

Provide `npm run dev`, `npm run check`, `npm test`, `npm run build`, and
`npm run preview`. Use `npm ci` for locked installs. TypeScript checking is
explicit; a successful Astro build alone is not evidence that types pass.
Astro, Observable Plot, TypeScript, and Astro's checker form the initial tool
set. Additional dependencies need agreement before they are added.

Build static HTML for the narrative and tables. Use Observable Plot for the
charts, with browser code limited to rendering, responsiveness, and useful
inspection. The narrative and exact values remain available if JavaScript is
disabled. Bundle dependencies and assets with the site rather than loading
chart libraries from third-party CDNs. Only ship data used by the page; the
full four-relation snapshot remains in source control.

Commit source, data, and lockfiles. Ignore `node_modules/` and `dist/`. Keep
components and chart helpers specific to these three questions; no plugin
system, generic chart registry, or general-purpose data access abstraction.

## 8. Deployment and updates

Publish `dashboard/dist/` to GitHub Pages using a separate GitHub Actions
workflow with an explicit manual trigger after review. Build and deploy the
same selected commit, including its data and narrative. The workflow installs
locked frontend dependencies, checks, tests, builds, and deploys the static
artifact. It never authenticates to GCP or starts Python pipeline services.

Use the repository's Pages URL initially, with Astro configured for the actual
site origin and repository base path. Navigation, scripts, data, and assets
must work beneath that path. A custom domain is optional future work.

Continuous integration for the dashboard is a separate workflow,
`.github/workflows/dashboard-ci.yml`, triggered on push to `main` and on pull
requests, filtered to `dashboard/**` and its own file. It runs `npm ci`,
`check`, `test`, and `build` on the pinned Node version. The existing `ci.yml`
is unchanged; it already covers the exporter's Python tests.

A warehouse refresh does not trigger a dashboard release. Updating the data
means preparing a new complete export, reviewing its claims and bounds, then
publishing a new site. A rollback republishes a previously reviewed commit
with its matching data. No automatic data refresh, separate data deployment,
or scheduled publication is part of this design.

## 9. Verification and acceptance

Write public function contracts, then focused tests, then implementation.
Tests use committed data and small synthetic edge cases without network or
cloud calls. Cover the JSON boundary, required view selections, partial-year
rendering, null handling, chart/table agreement, and numerical claims. Check
Q1 record claims against full history and Q3 claims against the fixed cell and
correct denominator. Do not mirror dbt's analytical test suite.

Before publication, type checks, tests, and the static build must pass. Review
the built site in a browser at desktop and narrow mobile widths, including
keyboard navigation, disclosures, chart labels, and JavaScript-disabled
content. Verify all three findings against the frozen inputs and confirm
repository-base-path behavior. Inspect network requests for accidental live
data calls or unnecessary large assets, and measure first-load behavior under
a throttled mobile connection; fix visible waiting and layout shifts before
acceptance rather than relying on the framework's reputation for speed.

Review the complete local experience before the first public deployment.
Implementation may proceed incrementally internally, but there are no required
public deployments for individual questions. After authorized publication,
smoke-check the public URL, charts, links, and assets. The deliverable is the
complete three-question presentation.

## 10. Implementation plan

Implement in five chunks. Each chunk is one implementation and review cycle;
the next starts only after review.

1. **Exporter and snapshot.** `tools/export_dashboard_snapshot.py`, its tests,
   and the `pyproject.toml` and `.env.example` changes. The owner then runs it
   against prod and commits `dashboard/data/`. Later chunks build on real data,
   and the snapshot is checked against the intended headlines early.
2. **Scaffold and data boundary.** The Astro project, npm scripts, pinned Node
   version, TypeScript row types, snapshot loader with `SnapshotDataError`,
   fixed-view checks, boundary tests, and `dashboard-ci.yml`. No visible page.
3. **Page layout and Q1.** Layout, typography, colours, introduction, Methods
   skeleton, provenance, and the complete Q1 section with chart, qualification,
   and exact-value table. This sets the patterns Q2 and Q3 follow, and is
   reviewed in the browser.
4. **Q2 and Q3.** Both sections, following chunk 3's patterns. Split them if
   chunk 3 shows a section is larger than expected.
5. **Acceptance and deployment.** Mobile, keyboard, disclosure, JavaScript-
   disabled, base-path, network, and throttled-load checks from §9, plus the
   manual Pages workflow. Ends with the complete local review; publication
   needs separate authorization.

Review of chunks 2–5 focuses on contracts, tests, and the rendered page against
this spec, not on TypeScript idiom.
