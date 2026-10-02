# Dashboard chunk 5 review

Reviewed 2026-10-03 against commit
`76a041d48f699a61924ce71f30208b31ba7f3d5e` plus the uncommitted
`.github/workflows/dashboard-pages.yml` and favicon addition in
`dashboard/src/pages/index.astro`. Requirements are the updated dashboard spec,
especially §§6, 8, and 9. This review includes the complete local presentation,
not just the two changed files.

**Recommendation: fix the remaining mobile chart issue and apply the owner's
table-formatting update before accepting the local experience.** No blocking
defect was found in the new workflow or favicon change. The chart issue is in
Q1 and predates this diff, but falls within chunk 5's full-page acceptance
scope. The final Q3 placement fix passes.

No application code, tests, dependencies, snapshot data, or remote settings were
changed during review. No workflow was dispatched and nothing was published.
D1's additional automated rendering tests remain deliberately declined.

## Remaining acceptance finding

### P2 — Q1's year labels overlap at 320px

**Location:** `dashboard/src/charts/q1-chart.ts:66–71`.

Q1 still asks Plot for five ticks on a narrow chart, leaving only 145px of
plotting width at a 320px viewport with a scrollbar. Plot chooses 1980, 1990,
2000, 2010, and 2020. Each label is approximately 33.72px wide while tick
centres are only 31.52px apart: adjacent text bounds overlap by about 2.20px.
The rendered axis reads as a continuous string of years. This reproduces on
a fresh load, not just after resizing.

[Screenshot at 320px](dashboard-chunk-5-review-assets/q1-320.png).

**Recommendation:** use an explicit sparse year array at narrow plotting
widths, as Q2 now does; for example 1980, 2000, and the snapshot's final year.
Preserve every observation and the separate partial-year annotation. Select
tick density from the plotting width after margins.

**Viable alternative:** reclaim the right-label gutter by relocating the
direct labels into a separate band, then choose a tick sequence that fits.
This requires a larger layout change than explicit ticks and is unnecessary
for this fixed view.

While touching this axis, use the existing percentage formatter for y ticks:
they currently show whole percentages, while spec §6 requires one decimal.
That is a smaller pre-existing consistency issue, not the cause of the year
collision. An explicit spec exemption for axis precision is an alternative,
but Q3 already follows the stated format.

**Acceptance:** Q1's years have visible separation at 320px including a
scrollbar, on initial load and resize; the percentage ticks fit at the required
precision; both lines, direct labels, dashed partial segments, and hollow
partial markers remain readable. Recheck 390px and desktop after the change.

### Owner-requested update — round table ratios

Added after the initial review: shares in all three tables and Ginis in Q3
should have at most three decimal places. This supersedes the former
full-stored-precision display requirement; it was not a defect against the
original spec.

**Recommendation:** use one table-ratio formatter that rounds to three decimal
places and trims trailing zeros. Keep shares as fractions: 0.3504 becomes
0.35, while 0.7506 becomes 0.751. Integer counts and ages remain unchanged;
undefined ratios remain explicitly undefined. Preserve full precision in the
snapshot, chart coordinates, and numerical-claim checks.

Rename the disclosures to “Values” or “Detailed values” and replace captions
that promise stored precision with “Ratios rounded to at most three decimal
places”. The dashboard spec now records this presentation contract.

**Viable alternative:** consistently show exactly three decimal places
(0.350, 0.751), if aligned trailing digits are preferred. Two decimal places
are also within the owner's requested range, but three better preserve the
small differences between the Q3 Ginis.

**Acceptance:** no table share or Gini displays more than three decimal
places; all rows and counts remain present; nulls do not become zero. The
earlier full-precision table comparisons below describe the reviewed version,
not the newly requested display format.

## Deployment workflow review

The workflow is structurally consistent with the approved design:

- Its only trigger is `workflow_dispatch`; there is no push, schedule, or
  warehouse trigger.
- Checkout uses the selected input ref. Node comes from the selected source's
  `.node-version`; dependencies come from its lockfile via `npm ci`.
- Checking, testing, and building run in order before artifact upload. The
  deploy job depends on the build and publishes that run's Pages artifact;
  it does not rebuild or fetch a second data snapshot.
- Build has repository read permission. Pages and OIDC write permissions are
  confined to the deployment job, which uses the `github-pages` environment.
- Deployment concurrency is serialized without cancelling a running release.
- There are no GCP credentials, Python pipeline commands, or dbt invocations.
- YAML parses successfully. The workflow's commands match the local frontend
  toolchain. Its GitHub-hosted execution was not tested by publishing.

### Decision: immutable release selection (nonblocking)

**Location:** `.github/workflows/dashboard-pages.yml:8–10, 29–31`.

The input accepts a SHA, branch, or tag. A full SHA identifies the reviewed
source exactly; a branch or movable tag can change between review, dispatch,
and checkout. The workflow still builds and deploys one consistent artifact,
but a moving ref weakens the claim that it is the reviewed source.

**Recommendation:** supply a full commit SHA for every publication and rollback.
Optionally restrict the input to that form and record the resolved checkout SHA
in the run summary. This is release clarity, not a blocker when a full SHA is
already supplied.

**Viable alternative:** retain branch/tag support, resolve the ref once at the
start, and prominently record the resolved SHA for the operator to compare with
the reviewed revision. That preserves convenience but still requires attention
to which revision was actually selected.

### Publication prerequisites, not verified by this local review

The repository's Pages source and `github-pages` environment configuration were
not inspected or changed. Confirm they permit the intended Actions deployment
before the first authorized run. A local build cannot demonstrate the remote
deployment permission/configuration path. Keep the first public smoke check
after publication as required by the spec; do not call this review evidence
that a deployment has succeeded.

## Local acceptance evidence

### Checks and data

- `npm run check`: passes, 25 files, no errors, warnings, or hints.
- `node --test --test-isolation=none 'test/**/*.test.ts'`: **70 tests in
  16 suites pass**. This exposes individual test results in this environment.
- `npm run build`: passes on Node **24.21.0**, matching `.node-version`.
- `git diff --check`: passes.
- Compared every rendered table cell against the frozen inputs: **94 Q1,
  42 Q2, and 11 Q3 rows agree**, including integer counts and stored ratios.
  Existing numerical-claim tests also pass for all three narratives.
- The snapshot and null-handling implementation have not changed. The earlier
  synthetic-null build exercise is not claimed as a new check in this pass.
  No fresh `npm ci` or GitHub runner execution was performed; the lockfile and
  dependencies are unchanged.

### Browser and interaction checks

Used headless Google Chrome against the built preview at
`http://127.0.0.1:4325/openalex-pipeline/`. Inspected all three charts at
1280, 768, 680, 640, 560, 390, and 320px while resizing a loaded page across
layout breakpoints. Also performed a fresh 320px load and a mobile-emulated
390px session.

- All three charts mount without runtime exceptions or failed requests.
  There is no page-level horizontal overflow at the tested widths.
- The final Q3 fix moves AI above Graphics with clear separation at 320px.
  Full mapped names, leader lines, and the other required labels remain
  readable. [Screenshot](dashboard-chunk-5-review-assets/q3-320.png).
- Q2's explicit narrow ticks, nested markers, and shared-endpoint annotation
  remain readable. The outstanding narrow-axis problem is confined to Q1.
- All four section anchors resolve to existing targets.
- Enter opens all three table disclosures; Tab reaches their scroll regions
  with a visible 3px outline. ArrowRight scrolling was exercised on Q2 and Q3;
  those tables scroll internally without expanding the mobile page.
- JavaScript-disabled content retains all narrative sections, noscript notices,
  and all 147 table rows. No chart SVG remains, as expected.
- With reduced motion emulated, the document's computed scroll behaviour is
  `auto`, rather than smooth scrolling.
- All observed page requests stay beneath the repository base path and consist
  of the page, local JavaScript modules, and the self-hosted font. There are no
  live data or third-party CDN calls. The favicon addition prevents the
  previous implicit `/favicon.ico` request; it adds no network request.

### Throttled mobile load

One cold-cache sample at 390px, with 150ms added latency, 200,000 bytes/s
download, 93,750 bytes/s upload, and 4× CPU throttling, produced:

- First contentful paint and LCP: approximately **0.37s**.
- All three chart SVGs present: approximately **1.23s**.
- Cumulative layout shift: **0** during the nine-second observation.
- Largest JavaScript transfer: approximately **86.5KB**, including overhead;
  font transfer: approximately **48.6KB**.

No visible waiting or layout-shift issue was found in this sample. These are
local-preview measurements, not a production performance guarantee or a
multi-sample benchmark.

## Completion boundary

Fix the Q1 axis, apply the table-formatting update, and recheck the affected
widths and displayed values to complete this local review.
The workflow and favicon change can otherwise proceed. Additional automated
rendering tests are not requested. Firefox/WebKit, physical-device touch, and
screen-reader behaviour were not exercised; this report does not claim a full
cross-browser or accessibility certification. Publication remains a separate
authorized action, followed by the public URL/assets smoke check.
