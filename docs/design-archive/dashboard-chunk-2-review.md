# Dashboard v1 implementation review

> **Archived.** Findings 1–3 were fixed and finding 4 was accepted as a
> narrower, documented error contract before chunk 2 was accepted. Items
> deferred to later chunks were folded into `docs/dashboard-spec.md`.

Reviewed 2026-10-02 against HEAD
`367953df9e9ad6f0b33ad45422f52ae091e2b023` and the untracked dashboard changes.

**Recommendation: address the three P2 findings before accepting chunk 2.**
The scaffold builds, its existing tests pass, and the committed data supports
the intended findings. The snapshot boundary nevertheless accepts contradictory
bounds, inconsistent partial-year flags, and an incomplete Q3 comparison cell.
There is also a P3 mismatch in file-error reporting.

This review changes documentation only. Suggested fixes below are not implemented.

## Scope

There was no tracked diff. The implementation under review consists of the new
`dashboard-ci.yml`, frontend configuration and lockfile, three source files,
and `snapshot.test.ts`. I read these files, the dashboard specification,
project overview, decisions and findings, and checked the row contracts against
the exporter and gold schemas. The already committed exporter and snapshot
were inputs to this review, not new implementation changes.

The code implements **chunk 2: scaffold and data boundary**. The page contains
only an export timestamp. Charts, narrative, tables, methods, styling and Pages
deployment are later chunks in the agreed plan; their absence is not a defect
in this chunk. This is not acceptance of the complete v1 dashboard.

## Findings

### 1. P2 — Recorded bounds are type-checked but not reconciled with the data

Locations: `dashboard/src/data/snapshot.ts:285–292`, `:325–327`,
`:359–370`, and `:379–386`.

`parseMeta` requires integer bounds, but neither it nor `parseSnapshot` checks
that they describe the loaded relations. Selectors use some bounds to filter
data, which can hide a metadata error instead of rejecting it. `year_min` and
`gini_cohort_min` are never used for validation.

Reproduced independently on copies of the committed snapshot:

<!-- prettier-ignore -->
| Mutation to `snapshot.json` | Observed result |
|---|---|
| `citation_age_year_min = 2026`, leaving maximum at 2025 | Accepted; Q2 contains zero rows; static build exits 0. |
| `citation_age_year_max = 2024` | Accepted; Q2 silently shrinks from 42 to 39 rows although the file still contains 2025. |
| `year_min = 1960` | Accepted despite Q1 data starting in 1950. |
| `gini_cohort_min = 2021` | Accepted while returning the supposedly out-of-bounds 2020 Q3 cell. |
| `gini_citation_year_max = 2026` | Accepted although both Q3 exports end in 2025. |

The specification explicitly assigns recorded-bounds validation to this
boundary. These cases can give the page false coverage labels or an empty
chart while CI stays green. Reject inverted bounds, reconcile the recorded
coverage with each relation, and require the fixed views to fall within it.
This should remain a boundary check, without recomputing gold statistics or
replicating its full analytical test suite.

Add focused tests for inverted ranges, metadata/data extent disagreements and
a fixed Q3 cell below the recorded cohort floor. Require a nonempty Q1/Q2
view rather than relying on loops to execute at least once.

### 2. P2 — One Q1 variant can lose its partial-year flag unnoticed

Location: `dashboard/src/data/snapshot.ts:343–345`.

The validator reduces flagged rows to a set of years. If only one of the two
2026 rows is flagged, that set is still exactly `{2026}` and validation passes.

Reproduction: set `is_partial_year = false` on the 2026 `strict` row, leaving
the `broad` row unchanged. `parseSnapshot` accepts it, Q1 returns all 94 rows
with inconsistent final-year flags, and the static build exits 0.

The intended chart and table consume these flags to distinguish provisional
data. This permits one series to appear complete while the other is partial.
Validate the flag on each row against its publication year and the recorded
partial year. Test either variant losing its flag as well as an earlier row
gaining one. The current test only covers a second flagged year, so it cannot
detect this case.

### 3. P2 — Q3 completeness checks cover labels, not the whole comparison

Location: `dashboard/src/data/snapshot.ts:388–398`.

The fixed view requires only the four directly labelled subfields. Other
classified subfields can disappear from the 2020/five-year cell without a
failure, provided the file's recorded row count agrees.

Reproduction: remove only the 2020/5 Software row
(`https://openalex.org/subfields/1712`) and decrement the recorded subfield row
count from 1001 to 1000. Parsing and the static build both succeed. Q3 now
returns ten subfields instead of eleven; Software still occurs elsewhere in
the relation.

The chart and table are specified to show every classified subfield in this
cell. Silently dropping a comparison point changes that population, even if
all four annotations survive. Validate the full reviewed cell membership,
with an explicit release-specific expectation or another agreed completeness
contract. Do not use the annotation list as the population contract. Add a
test deleting an unlabelled subfield while keeping the recorded count correct.
Continue retaining null-valued rows for the table and excluding the
unclassified bucket from this view.

### 4. P3 — Physical file failures bypass the promised snapshot error type

Location: `dashboard/src/data/load.ts:7–11`.

All five JSON files are static imports, so missing files and invalid JSON fail
in module resolution or Vite's JSON parser before `parseSnapshot` runs. The
unit test called “missing file” deletes a key from an already parsed object;
it does not exercise the actual loader.

In isolated build copies:

- Removing `gold_ai_share_by_year.json` exits 1 with `[UNRESOLVED_IMPORT]` and
  the path, not `SnapshotDataError`.
- Replacing its contents with `[{` exits 1 with a `builtin:vite-json` parsing
  error. The captured diagnostic does not identify the offending filename.
- Keeping valid JSON but setting a `share` to a string correctly exits 1 with
  `SnapshotDataError` naming the file, row and column.

This fails closed, so it is less severe than the accepted-invalid-data cases.
It still differs from the specified known-error contract. Put diagnosed file
absence and JSON syntax failures behind a build-time loader that can attach
the filename and throw `SnapshotDataError`, while propagating unrelated
failures. Alternatively, explicitly agree to and document the narrower error
contract. Add an actual loader/build test rather than another object-key test.

## Validation performed

Environment: Node `24.21.0`, npm `11.19.0`, matching the committed Node pin.
Mutation probes used cloned objects and isolated projects under
`/tmp/dashboard-v1-review/`; repository source and snapshot files were not
modified.

<!-- prettier-ignore -->
| Check | Result |
|---|---|
| Locked install in a fresh temporary project | `npm ci --offline --cache /home/nils/.npm --no-audit --no-fund` succeeded, installing 312 packages from cache. |
| `npm run check` | Passed: zero errors, warnings or hints; repeated successfully after the clean install. |
| `npm test` | Exit 0. The sandbox reporter summarized one test file; explicit in-process execution confirmed all 25 tests in three suites passed. |
| `node --test --test-isolation=none test/snapshot.test.ts` | 25 passed, zero failed; also passed in the clean-install copy. |
| `npm run build` | Passed in the workspace and clean-install copy. Output consists solely of a 253-byte `dist/index.html`. |
| Build with a string in a numeric column | Failed with the expected typed file/row/column diagnostic. |
| Builds with missing or malformed JSON | Failed; diagnostic-contract issue described in finding 4. |
| Builds with a missing partial flag, reversed Q2 bounds, or missing unlabelled Q3 row | Incorrectly succeeded, as described above. |
| Additional parser probes | Unsafe integers, nonfinite numbers and an unknown variant were rejected with `SnapshotDataError`. An injected unrelated exception propagated unchanged. |
| Existing null/unclassified tests | Null concentration measures remain in the Q3 selection; the unclassified bucket is excluded. |
| Preview under `/openalex-pipeline/` | HTTP 200 with the expected placeholder and document title. |
| Headless Chrome screenshots | Inspected at 1440×900 and 390×844; placeholder text is readable and fits both widths. |

The initial isolated install failed because the sandbox blocked esbuild's
binary check; the same install succeeded outside it. Browser startup and local
preview access also required execution outside the sandbox. These were
environment limitations, not implementation findings. The preview server was
stopped after testing.

The browser showed exactly:

> Snapshot exported 2026-10-01T10:46:52.981391Z.

The generated page has no scripts, stylesheet, client bundle, chart library
download or embedded relations. Its text is present directly in the HTML.
A JavaScript-disabled Chrome capture was attempted but produced no usable
artifact, so it is not counted as a completed browser check. Source inspection
does establish that this particular placeholder needs no JavaScript.

The configuration's origin and base agree with the repository remote. The CI
workflow has the specified push/PR path filters, uses the pinned Node file,
and runs install, check, test and build in `dashboard/`. It does not start the
pipeline or authenticate to GCP. This was a local review; GitHub Actions itself
was not run.

## Snapshot and analytical checks

The committed snapshot contains 154 Q1 rows, 42 Q2 rows, 1001 Q3 subfield rows
and 273 Q3 group rows. Selectors return 94, 42 and 11 rows respectively. The
export date is 2026-10-01; the pipeline revision is explicitly `unknown`.
Export time is not evidence of source freshness.

The checked numerical anchors agree with the specification and findings:

- Q1 strict/broad shares round to 35.0%/49.7% in 2025 and 39.8%/54.7% in
  partial 2026. Both full-history peaks occur in 2026. Among complete years,
  strict peaks in 1951 and broad in 2025.
- Q2 medians move from 8/7/7 in 2012 to 5/5/5 in 2025 for AI, CV/PR and rest
  of CS. Latest shares aged at most five round to 55.4%, 57.2% and 54.3%.
- Q3 uses cohort 2020 and cumulative age 5. AI has uncited share
  `0.4635886932464023` and cited-only Gini `0.7597182912465906`; CV/PR has
  `0.35252414711899893` and `0.7507292125859925`. Computer Graphics has
  `0.6748270356572645` and `0.7592592660622178`, supporting the intended
  comparison. All eleven current scatter rows have defined cited-only Ginis.

These checks validate publication inputs and the intended numerical claims;
there are no rendered analytical claims or charts to validate yet. They do not
reconcile the warehouse or underlying source records. No warehouse queries,
dbt builds or Dagster services were run.

## Additional observations and remaining acceptance work

Provenance validation is shallow beyond key presence: an empty source-table
string, a `source_modified_at` value of `"garbage"`, and an export timestamp
without a timezone all pass. The committed metadata is well formed. Before
Methods renders these fields, decide and document their semantic contract,
especially the promised UTC export timestamp and production source identity.

The row schemas match the enforced gold columns and nullability. The code
preserves stored measures, uses full subfield IDs, does not recompute
statistics, and keeps full relations out of the current client output.
These are appropriate boundaries to retain when addressing the findings.

Tests for the three accepted-invalid-data cases and real file loading are
missing. Chart/table agreement, partial-year rendering, null-point omissions,
and rendered numerical claims are also untested because that presentation has
not been implemented. Add them with the corresponding later chunks rather
than treating today's green suite as dashboard acceptance.

Desktop/mobile chart labels, keyboard navigation, disclosures, focus,
contrast, JavaScript-disabled reading of the complete story, asset paths under
the repository base, browser network requests, and throttled first-load/layout
stability still need the planned acceptance review. No performance conclusion
about the eventual dashboard follows from this 253-byte placeholder. The
manual deployment workflow and public URL smoke check remain later work;
nothing was published during this review.
