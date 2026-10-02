# Dashboard chunk 4 review

## Follow-up review — 2026-10-02

**Current recommendation: one remaining placement fix before acceptance.**
Findings 2–5 are resolved. Finding 1 is substantially improved, but AI and
Computer Graphics still collide at the narrowest tested width. D1's additional
rendering tests were deliberately declined by the owner; no action is required
on D1, and it is not an acceptance blocker. D2 and D3's recommended approaches
are reflected in the updated implementation.

### Remaining finding: separate AI and Graphics at 320px (P2)

**Location:** `dashboard/src/charts/q3-chart.ts:28–29`, the `NARROW` placements.

Both labels end at y=0.86. Wrapping Graphics onto two lines solves the larger
collision, but its second line still meets AI on the same baseline. In Chrome
at a 320px viewport with a 15px scrollbar, the usable chart width is 273px
and plotting width 201px. AI spans x=150.35–163.57; “Graphics & CAD” starts
at x=162.45. Their text bounds overlap by approximately **1.12px**, and the
rendered text reads like “AIGraphics & CAD”. There is no longer viewport
clipping. The 390px and wider layouts are clear.

Evidence: [remaining collision at 320px](dashboard-chunk-4-review-assets/recheck-q3-320.png),
[clear layout at 390px](dashboard-chunk-4-review-assets/recheck-q3-390.png).
The scrollbar detail matters: testing only a scrollbar-free mobile viewport
can miss this case.

**Recommendation:** raise the narrow AI label into its own vertical space
(for example, around y=0.94) and move its leader endpoint with it. Check the
actual render for clearance from both Graphics and the top axis area. This
keeps the approved names and domains and needs no new abstraction.

**Viable alternative:** wrap Graphics into three shorter lines and adjust
its position and leader accordingly. Keep a visible gap between labels rather
than merely eliminating the one-pixel intersection.

**Acceptance:** readable separation at a 320px viewport including a scrollbar,
on initial load and after resizing; no regression at 390px or desktop.

### Resolved findings and decisions

- **Finding 2:** Q2 now explicitly labels 2012, 2018, and 2025 on narrow plots.
  The 320px render has clear, nonoverlapping ticks and retains all annual
  observations. [Evidence](dashboard-chunk-4-review-assets/recheck-q2-320.png).
- **Finding 3:** all lines precede the marker layer, dash patterns distinguish
  groups, and differently sized markers reveal coincident groups. The shared
  endpoint has an “All: 5 years” annotation and bracket. These make the ties
  visible without hovering. [Desktop evidence](dashboard-chunk-4-review-assets/recheck-q2-1280.png).
- **Finding 4:** neutral points now use `#6b7280`, giving approximately **4.63:1**
  contrast against the paper background. They are visibly clearer.
- **Finding 5:** Q2 defines citation age using the recorded citation year and
  explicitly includes age zero. Methods now says “papers with no citations
  in that window”. Both contradictions are removed.
- **D1:** deliberately declined; existing tests plus manual browser review
  remain the chosen approach. No additional tests were added by this review.
- **D2:** the existing specific claim thresholds remain, with two added
  threshold-boundary tests. Both pass.
- **D3:** full 0–1 domains remain; five explicit ticks show one-decimal
  percentages and three-decimal Ginis. This follows the recommended option.

### Follow-up verification

- Type check passes with no diagnostics; static build passes.
- All **70 tests in 16 suites** pass using
  `node --test --test-isolation=none 'test/**/*.test.ts'`.
- Inspected the built site in Chrome at 1280, 768, 680, 640, 560, 390, and
  320px. This pass resized a single loaded page, exercising redraw and both
  sides of Q3's placement breakpoint. All three charts remained mounted;
  no runtime exceptions or failed network requests were recorded.
- Rechecked JavaScript-disabled content: all three tables and the narrative
  remain available. No data or application source was modified by this review.
- The earlier analytical, keyboard, null-fixture, and throttled-load results
  below are from the first pass; they were not all repeated. This follow-up
  concentrates on the revised presentation and wording, and does not complete
  chunk 5's broader acceptance work.

## Initial review — retained for context

The findings and recommendations below describe the first reviewed version.
The follow-up statuses above supersede them.

Reviewed 2026-10-02 against `a4f65fa2ff068ce29ef4efdee68fa27d0c75866e`
plus the uncommitted chunk 4 changes, including all ten new files. Scope:
Q2, Q3, Methods additions, navigation, styles, and the shared chart mounting
helper used by Q1. Requirements: dashboard spec §§4–7, 9, and chunk 4 in §10;
analytical interpretation checked against the frozen snapshot and FINDINGS.

**Recommendation: request changes before accepting chunk 4.** The numbers,
fixed populations, tables, and major qualifications are sound. The main
problems are visible in the charts: mobile annotation collisions, crowded year
ticks, hidden coincident series, and faint comparison points. Correct two
contradictory descriptions of citation time as well. These do not require
changing the data or analytical design.

No application code, snapshot, dependencies, or production state was changed
during review. This report and its screenshots are the review deliverables.

## Findings requiring changes

All five findings below are **P2**: material presentation or explanatory
problems, without evidence of incorrect stored calculations or a broken build.
The recommendations preserve the approved analytical views.

### 1. Q3 annotations collide on mobile and are clipped at 320px

**Location:** `dashboard/src/charts/q3-chart.ts:11–15, 42–52`.

The four labels use fixed desktop offsets at every width. At a 390px viewport,
“Computer Graphics & CAD” is painted across “AI”. At 320px, the CV/PR label
starts outside the left viewport and Information Systems extends beyond the
right edge. The required annotations are therefore unreadable even though
all eleven points exist and the page does not report horizontal overflow.
Checking `scrollWidth` alone would miss this.

In the 390px capture, the AI text spans approximately x=184–197 and the
Graphics text x=165–330 on effectively the same baseline. At 320px, CV/PR
starts at x=−15 and Information Systems ends at x=324. These captures include
a desktop-style scrollbar; the usable widths are 375px and 305px respectively.

Evidence: [390px](dashboard-chunk-4-review-assets/q3-390.png),
[320px](dashboard-chunk-4-review-assets/q3-320.png),
[desktop comparison](dashboard-chunk-4-review-assets/q3-1280.png).

**Recommendation:** keep the mandated names and add explicit narrow-layout
placements, multiline labels, and short leader lines where needed. Place the
four labels in separate regions around the point cluster, with enough top
space to avoid the axis title. This is a small, fixed chart; a generic label
collision engine is unnecessary.

**Viable alternative:** use a narrow-screen callout band within the figure,
with each full label connected to its point. This uses more height but keeps
the approved labels. Abbreviating the mapped names would require a spec
decision; removing labels or relying on tooltips would not meet the contract.

**Acceptance:** all four names remain legible and unambiguously attached to
their points at 320, 390, 768, and 1280px, including after resizing. Test label
bounds and intersections, not only page overflow.

### 2. Q2's year ticks run together at narrow widths

**Location:** `dashboard/src/charts/q2-chart.ts:40–45`.

The narrow branch asks Plot for five ticks, but this is a suggested tick count,
not a maximum. With the fixed 44px left and 90px right margins, Plot still
chooses 2012, 2014, …, 2024. At 320px, these seven four-digit labels overlap
across an approximately 139px plotting area. They are also too tightly packed
in the 390px capture. Annual markers are preserved correctly; only the axis
labelling is defective.

Evidence: [320px Q2](dashboard-chunk-4-review-assets/q2-320.png).

**Recommendation:** supply a small explicit tick array for narrow screens,
including the endpoints—for this snapshot, 2012, 2018, and 2025. Keep all annual
observations in the chart. Select tick density using the available plotting
width rather than the full container width.

**Viable alternative:** move the direct labels into a band above or below the
plot, reclaiming the 90px right gutter, then use a wider-spaced tick sequence.
Rotated labels are possible but less readable for this short essay.

**Acceptance:** no overlapping year text at 320px; first and last displayed
years can be identified without consulting the paragraph or opening a table.

### 3. Coincident Q2 lines conceal group identity

**Location:** `dashboard/src/charts/q2-chart.ts:16–26`.

Each group is drawn as a solid line followed by equally sized, paper-filled
markers. Later groups paint over earlier groups. In 2019–2021 the AI and rest
of CS medians coincide, and the shared segment looks green. In 2023–2025 all
three coincide at five: the line again looks green, with only fragments of
the underlying marker shapes. Spreading the final text labels does not reveal
the hidden series along the shared segments. This weakens the spec's “all
visible” requirement and the non-colour encoding described in the caption.

Evidence: [desktop Q2](dashboard-chunk-4-review-assets/q2-1280.png).

**Recommendation:** give the series distinct dash patterns and draw all lines
before the marker layer. Design coincident markers deliberately, using
different sizes or outlines so that a circle cannot erase a square. Add a
brief shared-endpoint annotation such as “All three: 5 years” with connectors
to the three direct labels. Verify the overlapping intervals in monochrome.

**Viable alternative:** annotate the tied intervals explicitly, keeping the
current geometry and showing group-specific symbol samples beside the direct
labels. Small multiples would solve occlusion but depart from the approved
single overlaid chart and would need a design amendment. Do not jitter the
underlying ages: that would imply numerical differences that do not exist.

**Acceptance:** a reader can tell that AI shares the rest-of-CS trajectory in
2019–2021 and that all three coincide in 2023–2025 without hover or table use.

### 4. Q3's neutral points have insufficient visual contrast

**Location:** `dashboard/src/charts/q3-chart.ts:34`, using
`dashboard/src/palette.ts:12` (`COLORS.neutral`).

The nine other subfields use `#9ca3af` dots against `#fbfaf7`, approximately
**2.43:1** contrast. These points carry the comparison, rather than decorative
information, and are already small. The pale grid further reduces their
visual separation. The palette token predates this diff, but Q3 introduces
this use of it for essential marks.

**Recommendation:** darken the neutral fill enough to exceed a 3:1 graphical
contrast target, with a little margin. Preserve the distinct AI/CV shapes and
colours. Recheck against both the paper and grid colours.

**Viable alternative:** retain the pale fill and add a sufficiently dark
outline, at a stroke width that remains visible on a five-pixel-radius dot.
That is a smaller visual change but requires checking actual rendering at
ordinary and high pixel density. Increasing dot size alone does not correct
the contrast ratio.

**Acceptance:** neutral marks remain easy to locate without hover, and their
fill or meaningful outline clears the chosen contrast threshold. This is a
targeted finding, not a claim of a complete accessibility certification.

### 5. Two sentences contradict the intended time definitions

**Locations:** `dashboard/src/components/Q2.astro:21` and
`dashboard/src/components/Methods.astro:34`.

Q2 opens with “Each citation links a citing paper to an older cited one; the
gap between their publication years is the citation's age.” The implementation
actually uses the annual citation-event year from `counts_by_year` minus the
cited work's publication year. Individual citing papers are not available in
this input. In addition, “older” excludes same-calendar-year citations in
ordinary reading, although age zero is explicitly included later.

Methods says that the cohort denominator includes “those never cited”. The
quantity is papers without citations **during 2021–2025**. A paper cited in
2020 or later outside the window can still be an uncited paper for this chart.
The nearby Q3 qualification correctly says “not never cited”; Methods should
not reintroduce the opposite interpretation.

**Recommendation:** replace the Q2 opening with “Citation age is the year a
citation was recorded minus the cited work's publication year; same-year
citations have age zero.” In Methods, use “including papers with no citations
in that window”. The rest of the weighting and denominator explanations can
stay.

**Viable alternative:** remove the Q2 definition from the opening and let the
existing qualification define calendar-year age. Keep the opening focused on
the 2012-to-2025 finding. For Methods, “including papers uncited in 2021–2025”
is equally precise. No change to the analytical model is recommended.

**Acceptance:** every definition refers to annual citation events and a
specified observation window; no sentence implies lifetime noncitation or
access to individual citing-paper records.

## Decisions and follow-up recommendations

### D1. Preserve rendering checks in the repository

**Location:** `dashboard/test/q2.test.ts`, `dashboard/test/q3.test.ts`.

The new tests exercise selections, helper outputs, label offsets, numerical
claims, and one omitted-point case. They do not render the Astro components
or SVGs. For example, changing a table column to the wrong property, deleting
the omission sentence, or making labels overlap would leave those helper
tests green. The review's independent rendered-table comparison and temporary
null build both pass, so this is a durability gap rather than a currently
incorrect table.

**Recommendation:** retain a focused build-level regression check for Q2/Q3
table values, embedded chart points, and the synthetic null row. Include a
headline-bearing null case that must stop the build. Keep a repeatable browser
check for the two narrow-width defects. Use the existing toolchain where
possible; a new browser-test dependency needs separate agreement.

**Viable alternative:** retain the helper tests and adopt an explicit manual
browser checklist with saved screenshots for each release. That avoids added
tooling but accepts weaker regression protection. The section-level null and
chart/table contracts should not be deferred entirely to chunk 5.

### D2. Confirm the authored numerical thresholds behind Q3's prose

**Location:** `dashboard/src/sections/q3.ts:67–102`.

The implementation translates “high concentration” into the top three
cited-only Ginis; “relatively broad reach” into an uncited share below the
median subfield; “similar” into a Gini difference below 0.01; and
“substantially larger” into an uncited-share gap of at least 0.10. These checks
are explicit, use unrounded values, and pass for the reviewed cell. They are
editorial thresholds introduced by the implementation, not definitions fixed
by the spec. An exact 0.01 Gini gap fails, while an exact 0.10 share gap passes.

**Recommendation:** approve these as release guardrails and pin their boundary
behaviour with small tests. They appropriately stop a changed snapshot for
human content review. Keep them specific; no configurable claims framework is
needed.

**Viable alternative:** replace the qualitative comparison with exact ranks
and the percentage-point gap, then guard those concrete claims. This is more
auditable but makes the opening denser. Removing all guards would weaken the
spec's requirement to stop when the snapshot no longer supports the story.

### D3. Choose Q3's axis scale and tick precision deliberately

**Location:** `dashboard/src/charts/q3-chart.ts:30–31`.

Both axes span 0–1. In the committed cell, the points occupy roughly
35–68% uncited and 0.64–0.76 cited-only Gini, leaving most of the plot empty.
The full scale supplies useful context but compresses the comparisons. This
also increases the pressure on mobile labels. The y ticks currently show one
decimal and x ticks whole percentages, whereas spec §6 requests three-decimal
Ginis and one-decimal percentages in charts and prose.

**Recommendation:** retain the full domains for this release, solve labels
explicitly, and format ticks to the approved precision with fewer ticks where
necessary. The chart then makes the bounded nature of both measures clear
without visually amplifying small Gini differences.

**Viable alternative:** approve a clearly labelled, fixed tighter domain
(for example x=0.3–0.75 and y=0.6–0.8) with a build-time range guard. This makes
the subfield pattern easier to inspect but magnifies small differences and
requires a new layout review. Alternatively, explicitly amend §6 to exempt
axis ticks from prose precision. Do not silently treat either choice as an
implemented requirement.

## Verification performed

### Automated and analytical checks

- `npm run check`: passes, 25 files, no diagnostics.
- `npm test`: passes. An additional
  `node --test --test-isolation=none 'test/**/*.test.ts'` run exposes and passes
  all **68 tests in 15 suites**; the ordinary invocation in this environment
  reported only five file-level results.
- `npm run build`: passes against the actual uncommitted working tree.
- Node used: **24.21.0**. No dependency installation or lockfile change.
- Compared every cell of the **42 rendered Q2 rows** and **11 rendered Q3
  rows** to committed source values, including counts and stored precision:
  exact agreement.
- Q2 medians are 8→5 for AI and 7→5 for each other group; latest supporting
  shares format to 55.4%, 57.2%, and 54.3%.
- Q3 selects the 2020 cohort, cumulative ages 1–5, excludes unclassified
  subfields, and plots 11 points. AI formats to 46.4% / 0.760, CV/PR to
  35.3% / 0.751, and Graphics to 67.5% / 0.759. Highlight and annotation
  identity comes from IDs; table names retain published names. Other names
  remain available in tooltips and the table.
- Built an isolated temporary copy with Software's window citations set to
  zero and its five nullable ratios set to null. The build succeeds, retains
  **11 table rows**, emits **10 chart points**, renders five `undefined`
  ratio cells, and states that one subfield is omitted. Original data remained
  untouched. This checks presentation behaviour, not gold's statistical tests.

### Browser test drive

Used headless Google Chrome against the built Astro preview at
`http://127.0.0.1:4322/openalex-pipeline/`. Tested viewport widths 1280, 768,
390, and 320px and a separate mobile-emulated 390px session.

- All three SVG charts mount, including Q1 after the shared-helper refactor.
  The observed browser run contains no runtime exceptions or failed network
  requests. The screenshot series confirms initial rendering at each width;
  continuous resizing was not separately asserted.
- New section anchors point to the correct section IDs. Assets load beneath
  the repository base path. Requests were local HTML, JavaScript, and the
  self-hosted font; no live data service or third-party CDN was contacted.
  The large shared bundle's `snapshot` filename does not indicate shipped
  raw relations: inspected output contains neither their table names nor the
  example raw count checked. The embedded chart payloads use selected views.
- Enter opens both new disclosures; Tab focuses each scroll region; focus
  shows a 3px outline; ArrowRight scrolls the table horizontally. At 390px,
  opening either wide table leaves page width at 390px.
- With JavaScript disabled, all three narrative sections, noscript notices,
  and tables remain in the built page: 94 Q1 rows, 42 Q2 rows, 11 Q3 rows.
  Charts are absent as expected.
- No page-level horizontal scrolling was observed. This does **not** excuse
  the Q3 text clipping documented above.
- One cold-cache mobile load used 150ms added latency, 200,000 bytes/s download,
  93,750 bytes/s upload, and 4× CPU throttling. Observed first contentful paint
  and LCP were about **0.37s**, all three charts existed by **1.11s**, and CLS
  was **0** during the nine-second observation. This is a local preview smoke
  measurement, not a production performance guarantee. The largest script
  transferred about 84KB including overhead; the font about 49KB. No visible
  layout-shift problem was detected in this run.

### Scope limits

This is a chunk 4 review with early acceptance checks, not completion of
chunk 5. Firefox/WebKit, physical touch devices, screen-reader output, a full
contrast audit, repeated performance samples, and the deployed Pages site
were not tested. No publication or warehouse refresh occurred. The committed
tests establish current behaviour; they cannot establish whether contracts
and tests were authored before implementation.

## Suggested acceptance sequence

1. Decide the options in findings 1–5 and D1–D3; implement the agreed fixes.
2. Re-run the focused rendering/data checks and browser review at 320/390px,
   then confirm desktop placement and Q1 still work.
3. Accept chunk 4 once chart identities, labels, contrast, and time definitions
   are clear. Carry the remaining cross-browser and publication acceptance
   work into chunk 5; public deployment still needs separate authorization.
