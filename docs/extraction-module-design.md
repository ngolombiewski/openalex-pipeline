# Extraction Module Design — Stages 1 & 2

Decisions, invariants, and structure for the OpenAlex `works` extraction
module. Stages 1 (policy and invariants) and 2 (module structure) are closed.
Stage 3 (concrete signatures and docstrings) follows from this document.

## Purpose

Extract OpenAlex `works` records for the Computer Science field and land them
as raw page files on local disk. This is the raw-extraction stage — records
are landed verbatim, with no transformation. Bronze status begins downstream
at Parquet.

The module supports an idempotent, resumable job invoked manually, once per
day, until the full subset is on disk. Downstream (Polars -> Parquet -> GCS ->
BigQuery) is out of scope.

## Operational Model

- Invocation: manual CLI, once per day. No cron or Dagster for now, but the
  core raises typed exceptions so an orchestrator can wrap it later without a
  deep refactor.
- Shard unit: one calendar year. The run is specified by a constant query
  plus a year range; each year is paginated independently with `cursor=*`.
- Sequential processing. The OpenAlex daily credit budget (~2 M records) is
  the bottleneck, not wall time. The largest year (~1.5 M records) always
  fits in one day's budget, so a year started fresh always completes in one
  run.
- Free credit tier. Per-year sharding leaves process parallelism available as
  an escape hatch if ever needed.

## Query Spec

The unit of query identity is the **query spec**: filter + `select` +
`per_page`. Anything whose change would invalidate existing pagefiles or
cursors is part of it.

- `filter` — the complete OpenAlex filter string, **including the year
  clause**. The run holds a filter template; each year's effective filter is
  the template with that year bound in. Changes the result set.
- `select` — the column list from DATA_MODEL. Changes record content.
- `per_page` — changes page boundaries, invalidating ordinals and cursors.

A year's `_META.json` records that year's *complete* effective query string
(the full OpenAlex query minus the `https://api.openalex.org/` prefix), so
per-year recorded specs differ from each other by construction. Any operation
on a year requires the run's year-bound query spec to match the recorded one;
a mismatch is a loud failure. The module never mixes data from different
query specs.

## Data Layout

Each year gets its own subdirectory under the output root:

    {root}/{year}/{pagefile}

- Pagefiles are named by ordinal, one result page per file, in JSONL format
  (one record per line, landed verbatim from the OpenAlex response).
- `_META.json` — the full query spec, `expected_count` (`meta.count` from the
  first response), `started_at`. Written once with the first page, then
  immutable.
- `_CURSOR` — JSON object `{next_cursor, next_page}`: the cursor token for
  the next fetch and the ordinal of the page it will produce. Initialised to
  `{next_cursor: "*", next_page: 0}`, updated after each page. Never deleted;
  retained after completion.
- `_YEAR_REPORT.json` — written when the cursor walk finishes (regardless of
  reconciliation outcome). Records year, complete query string,
  `expected_count`, actual record count, page count, `started_at`,
  `ended_at`, and the `reconciled` flag. A statement that *the download
  finished*.
- `_SUCCESS` — empty marker, written only when the download finished **and**
  the record count reconciled cleanly against `expected_count`. A statement
  that *the year is trustworthy*.

`_YEAR_REPORT.json` and `_SUCCESS` answer different questions and come apart
in the count-mismatch case (see State Model). `_SUCCESS` has exactly one job:
it is the bit that splits a finished year into "reconciled" vs "not".

Sentinel files use a leading underscore to stay separable from pagefiles.

JSONL is chosen so that resume and reconciliation are line operations rather
than full-array parses. Records are still landed exactly as the API returns
them — no fields added, none dropped.

## State Model

A year directory is in exactly one of four sound states. Classification is
based on these predicates: `_META.json` present with matching query spec (M),
`_CURSOR` present (C), at least one pagefile (P), `_YEAR_REPORT.json` present
(R), `_SUCCESS` present (S).

    Fresh         dir absent or empty            -> start the year
    InProgress    M, C, P, no R                  -> resume
    Complete      R present, S present           -> skip (trustworthy)
    CountMismatch R present, S absent            -> skip (download done,
                                                     count unreconciled —
                                                     surfaced loudly in the
                                                     RunReport)

`Complete` and `CountMismatch` are both terminal: the cursor walk has
finished and there is nothing to resume. They differ only in trust. The
worker skips both; the runner reports a `CountMismatch` year as a loud,
itemized finding ("finished with N records, expected M — accept or wipe").

Resolving a `CountMismatch` is outside the module (consistent with I7): the
user either accepts the year (manually write `_SUCCESS`) or wipes the
directory so the next run treats it as `Fresh`. The module never resolves it
and never silently papers over it.

Pathological directories are not states — they raise:

- Query-spec mismatch -> `QueryMismatch`
- Any other invariant violation -> `CorruptedYearState`

Decision rule (implemented in `storage.classify_year`):

    if dir absent or empty:
        return Fresh
    read _META.json; if present and query spec mismatches:
        raise QueryMismatch
    if _YEAR_REPORT.json exists:
        if _META present and matches:
            return Complete if _SUCCESS exists else CountMismatch
        else:
            raise CorruptedYearState
    else:
        if _META present and _CURSOR present and >=1 pagefile and matches:
            return InProgress(cursor, next_page, last_page_ordinal)
        else:
            raise CorruptedYearState  (diagnostic names the failed predicate)

`classify_year` returns only sound states. Both pathologies raise from
storage — the layer that holds the on-disk query spec and is therefore the
only one positioned to detect a mismatch. The worker pattern-matches four
clean arms with no error arm.

`_YEAR_REPORT.json` is the discriminator for "download finished"; `_SUCCESS`,
given the report, is the discriminator for "reconciled". `classify_year` does
not re-verify I5 in the terminal branches: the write order guarantees
`_YEAR_REPORT.json` is never written before pagefiles exist, so re-checking
would only defend against a module bug, which is not what corruption
detection is for.

Notes:

- Empty-result years (well-formed query, zero matches) need no special
  branching: write one pagefile containing zero lines, update `_CURSOR`,
  write `_YEAR_REPORT.json`, write `_SUCCESS` (`expected_count` 0 reconciles
  against actual 0). The "complete year has >=1 pagefile" invariant holds.
- The module does not repair corrupted states. Running on a clean output
  directory is the user's responsibility.

## Invariants

- I1. A year directory is in exactly one of: Fresh, InProgress, Complete,
  CountMismatch.
- I2. `_YEAR_REPORT.json` signals that the download finished; `_SUCCESS`
  signals that it also reconciled. `_SUCCESS` is never present without
  `_YEAR_REPORT.json`.
- I3. `_META.json` records the complete query string; any operation on the
  year requires a query-spec match.
- I4. `_CURSOR` holds the next cursor token and the ordinal of the page it
  produces; meaningful only before the download finishes.
- I5. An InProgress, Complete, or CountMismatch year has at least one
  pagefile.
- I6. Resumption is safe: it either completes the year correctly or fails
  loudly with a diagnosable reason. It never silently produces wrong data.
- I7. The module owns `_META.json`, `_CURSOR`, `_YEAR_REPORT.json`,
  `_SUCCESS`, and pagefiles. Other files are ignored. Filesystem hygiene —
  and resolving a CountMismatch — is the user's responsibility.

## Crash Safety

- Pagefile and `_CURSOR` writes are atomic: write to `.tmp`, flush, rename.
  (No `fsync` — too slow.)
- Per-page write order is: write pagefile, then update `_CURSOR`. A crash
  between the two leaves a pagefile whose cursor was not recorded.
- `_CURSOR` carries `next_page`, the ordinal it expects to produce. On resume,
  let `L` = highest pagefile ordinal on disk, `P` = `_CURSOR.next_page`:
    - `P == L + 1` -> clean. Resume normally.
    - `P == L`     -> crashed before the cursor update. The cursor is stale by
                      one; re-fetch and overwrite page `L`, then proceed.
    - otherwise    -> genuine corruption; raise `CorruptedYearState`.
  The check is O(1) arithmetic on filenames plus a small JSON read — no
  pagefile-content parsing.
- `tmp+rename` for single writes plus the `next_page` check for the
  cross-write window together cover the relevant crash points.

## End-of-Year Reconciliation

When the cursor walk reaches exhaustion (`next_cursor` null), the year is
done downloading. Before the year can be called trustworthy, the records
actually landed are reconciled against `expected_count` from `_META.json`.
This guards against silent data loss — a deficit that would quietly bias the
distributional analyses (Gini, citation half-life) downstream without ever
announcing itself.

End-of-year flow in `process_year`:

    walk cursor to exhaustion, writing pages + _CURSOR
    count records across all pagefiles (line count)
    write _YEAR_REPORT.json        (always — it records reality either way)
    if actual count == expected_count:
        write _SUCCESS
        return YearReport(..., reconciled=True)
    else:
        log ERROR with the delta
        return YearReport(..., reconciled=False)   # no _SUCCESS, no raise

Key properties:

- A count mismatch **blocks `_SUCCESS`** but does **not** raise. The year is
  genuinely finished — there is nothing broken and nothing to resume — so the
  run continues to the next year. The mismatch surfaces through the
  `RunReport` (built from the filesystem, which sees the missing `_SUCCESS`),
  not through control flow. This preserves the "one codepath independent of
  exit" property.
- `_YEAR_REPORT.json` is written in both cases; `_SUCCESS` only on a clean
  reconciliation. This is exactly what produces the `CountMismatch` state.
- Criterion (V1): **strict equality**. EDA shows `meta.count` stable for all
  but the current year. If small index drift is observed in practice, a
  tolerance margin is a one-line change to the single comparison — to be set
  from observed magnitude, not guessed in advance.

## Error Handling

- HTTP 429 (daily credits exhausted): raise `CreditsExhausted`. It propagates
  through worker and runner untouched; the CLI entrypoint catches it and
  exits 0. Expected end-of-day outcome.
- HTTP 403 (sub-second burst limit): exponential backoff, retry up to
  `MAX_RETRIES`. Transient.
- HTTP 5xx, timeout, connection reset: exponential backoff, retry up to
  `MAX_RETRIES`. Transient. On exhaustion, raise `TransientFailure`.
- HTTP 4xx other than 403/429: fail loudly. Likely a configuration bug.

429-vs-403 disambiguation is confirmed by the OpenAlex docs and local EDA:
429 is always daily exhaustion, 403 is always the burst limit.

## Module Structure

Four units, composed top-down, plus shared leaf modules:

    runner        orchestrates years, owns the loop and fetcher lifetime
      |
    year_worker   owns one year's state machine
      |
    fetcher       owns HTTP: one cursor in, one page out
      |
    storage       owns the filesystem: atomic reads/writes, classification

Responsibilities:

- storage — the only layer that knows the on-disk format. Implements
  `classify_year` (returns sound `YearState`, raises `QueryMismatch` /
  `CorruptedYearState`), all atomic writes, and `build_run_report` (a pure
  filesystem scan). Enforces I1, I2, I4, I5, I6, I7.
- fetcher — stateless w.r.t. disk. "Given a cursor, return the next page."
  Owns retry/backoff and the 429/403 translation into typed exceptions.
- year_worker — drives one year's state machine: asks storage for state,
  decides transitions, calls the fetcher, calls storage to persist, performs
  end-of-year reconciliation. Raises nothing of its own; propagates. Enforces
  I3, I6. Returns a `YearReport`.
- runner — thin loop over years in configured order. Creates the fetcher once
  and owns its lifetime. Builds the `RunReport` from the filesystem at exit.
  The only layer a future Dagster wrapper would replace.

### File layout

    extraction/
      settings.py    Settings (pydantic-settings); query-spec assembly;
                     SELECT and PER_PAGE constants
      types.py       YearState (Fresh | InProgress | Complete |
                     CountMismatch), YearReport, RunReport — frozen
                     dataclasses
      errors.py      exception hierarchy
      storage.py     filesystem layer
      fetcher.py     make_fetcher (context manager) + the closure
      worker.py      process_year
      runner.py      run
      __main__.py    CLI entrypoint: build Settings, call run, map
                     exceptions to exit codes

Dependency rule, strictly inward, no cycles: `errors` and `types` import
nothing internal; `settings` imports nothing internal; `storage` and
`fetcher` import `errors` + `types` + `settings`; `worker` adds `storage` +
`fetcher`; `runner` adds `worker`; `__main__` adds `runner`.

### Public surface per unit

- storage — public: `classify_year`, `write_page`, `write_cursor`,
  `read_cursor`, `write_meta`, `write_year_report`, `mark_success`,
  `build_run_report`. All format knowledge (sentinel names, pagefile naming,
  tmp+rename) is private. The worker calls verbs and never constructs a path.
  Test of the boundary: `worker.py` contains zero string literals naming a
  file.
- fetcher — public: `make_fetcher` only. The yielded callable's signature
  (`fetch_page(cursor: str) -> Page`) is public by value. Retry/backoff is
  private inside the closure.
- worker — public: `process_year`.
- runner — public: `run`.
- settings — public: `Settings` and its constructor.

### Key enforcement mechanism

State classification is a single `storage` function returning a tagged union:

    YearState = Fresh | InProgress(cursor, next_page, last_page_ordinal)
              | Complete | CountMismatch

Every entry point that touches a year starts with `classify_year` and
pattern-matches on the result. There is no other path: no scattered
filesystem probes, no ad-hoc cursor checks. Invariants can only be violated
in the one layer that owns them.

## Implementation Style

Classless by default; the design is shaped that way because the filesystem
carries run state, leaving most functionality close to pure.

    storage             module of pure functions      no state to carry
    year_worker         function, fetcher injected     state in filesystem
    fetcher             closure from make_fetcher       one long-lived resource
    runner              function                       thin loop
    Settings            pydantic-settings class         env loading + validation
    YearState, reports  frozen dataclasses              dumb typed containers

- `Settings` is the one genuine class: `pydantic-settings` `BaseSettings` for
  env loading, type coercion, fail-loud startup validation, immutability.
  Passed down explicitly, never a global.
- `YearState` variants, `YearReport`, `RunReport` are `@dataclass(frozen=True)`
  — internal containers that never cross a serialization boundary.
- The fetcher is a closure, not an `@lru_cache` singleton. `make_fetcher` is a
  context manager that opens a long-lived `httpx.Client` and yields a
  `fetch_page` callable closed over it. `runner.run` scopes it with `with`, so
  the client is closed on block exit including on exception. This is a
  structural requirement, not advice.
- `process_year` receives the `fetch_page` callable, not the fetcher or the
  client — it cannot outlive or re-open the resource.
- The fetcher is injected into `worker` and `runner`, never imported. This is
  the seam the test suite depends on: a fake fetcher (any callable) exercises
  the full state machine offline. Protecting this seam is a hard requirement
  through Stage 3.

## Reports

Reports are durable on disk, not accumulated in memory. A list of
`YearReport`s threaded through `runner` would not survive a `CreditsExhausted`
blowing past the return; a report file on disk cannot disagree with disk.
This applies the design's core principle — the filesystem is the state — to
reporting.

- `_YEAR_REPORT.json` — written by `process_year` when a year's download
  finishes, atomically, as a per-year sentinel. Contains: year, complete
  query string, `expected_count`, actual record count, page count,
  `started_at`, `ended_at`, `reconciled` flag. The durable record.
- `YearReport` (frozen dataclass) — the in-memory image of that file.
  `process_year` returns it on the happy path for the runner's own logging;
  the file is the authoritative copy, so the dataclass becoming unreachable
  on an exception costs nothing.
- `RunReport` (frozen dataclass) — built by `storage.build_run_report`, a
  pure filesystem scan over the output root: every year with
  `_YEAR_REPORT.json` is done (load it; `reconciled` distinguishes Complete
  from CountMismatch), the `InProgress` year is the partial, every configured
  year with no directory is pending. It is a *query over the filesystem*
  computed once at exit, never a running accumulation.

Because `RunReport` is a filesystem query, it is correct regardless of how
the run ended:

    run():
        try:
            for year in years:
                process_year(year, ...)        # writes _YEAR_REPORT.json
        except CreditsExhausted:
            pass                                # expected; fall through
        finally:
            report = build_run_report(root, configured_years)
            log(report)
        return report

`build_run_report` reads disk and does not care how the loop ended — clean
completion, `CreditsExhausted`, or a propagating `CorruptedYearState` (with
`build_run_report` in `finally`, the exception continues after the report is
logged). No catching-and-delaying, no exception juggling, no list threaded
through. The only `except` is the one already needed for `CreditsExhausted`.

Return types:

- `process_year(...) -> YearReport`. The non-exceptional outcomes are "year
  reconciled" and "year finished with a count mismatch" — both return a
  `YearReport` (the `reconciled` flag distinguishes them). `CreditsExhausted`
  is raised, not returned.
- `run(...) -> RunReport`.

## Exception Taxonomy

Single base, never raised directly:

    ExtractionError
      ConfigError          bad/missing env or malformed query spec — pre-flight
      QueryMismatch        _META.json query spec != run's query spec
      CorruptedYearState   year dir violates an invariant
      CreditsExhausted     HTTP 429 — expected end-of-day stop
      TransientFailure     retries exhausted on 403 / 5xx / timeout

Who raises what:

- `ConfigError` — `settings.py`, at construction. Nothing else runs if it
  fires.
- `QueryMismatch`, `CorruptedYearState` — `storage.py`, from `classify_year`.
- `CreditsExhausted`, `TransientFailure` — `fetcher.py`, the only layer
  touching HTTP.
- `worker` and `runner` raise nothing of their own; they propagate.

The common base lets the entrypoint catch `ExtractionError` as a category
distinct from genuine bugs (`KeyError`, etc.), which should crash with a
traceback.

## CLI Entrypoint

`__main__.py` is the single place exceptions become exit codes:

    clean completion        -> 0
    CreditsExhausted        -> 0   (expected; log final state)
    ConfigError             -> non-zero (distinct code)
    QueryMismatch           -> non-zero (distinct code)
    CorruptedYearState      -> non-zero (distinct code)
    TransientFailure        -> non-zero (distinct code)
    any other exception     -> uncaught; crashes with traceback (a bug)

Distinct non-zero codes let a future cron wrapper distinguish "out of credits,
fine" from "broken, page me". A Dagster wrapper would reuse the same
exceptions with a different mapping (e.g. `CreditsExhausted` -> reschedule);
`runner.run` stays orchestrator-agnostic.

## Configuration Surface

All environment configuration loaded once into a frozen `Settings` object.

Required (no default; `ConfigError` if absent):

- `OPENALEX_API_KEY`
- output root path
- year range
- filter

Optional (sane defaults):

- `MAX_RETRIES`, base backoff delay
- log level (default INFO)

Not environment config — module constants in `settings.py`:

- `select` — the DATA_MODEL column list. A data-model decision, not a
  deployment knob; a wrong value silently lands wrong columns.
- `per_page` — default 200 (OpenAlex max).

The query spec (filter + `SELECT` + `PER_PAGE`) is assembled in `settings.py`
so there is a single place the effective query is constructed and a single
object to hand to storage for the match check.

## Observability

Structured logs via loguru; structured fields via `bind()`, not string
interpolation, so a sink can filter on `year`.

- INFO, per year start: year, resolved query spec, classified state
  (fresh / in-progress-from-page-N / already-done).
- INFO, per page (the checkpoint line): year, page ordinal, records in page,
  cumulative count. The `(year, page_ordinal, cumulative_count)` triple plus
  the filesystem is enough to reconstruct run progress after a crash.
- INFO, per year end: `YearReport` contents, including the reconciliation
  outcome.
- INFO, run end: `RunReport` — years reconciled, years finished with a count
  mismatch, the in-progress year, years pending.
- INFO, on `CreditsExhausted`: final state — last year, last page, what
  remains. Expected, not an error.
- WARNING: retry attempts on 403 / 5xx backoff.
- ERROR: count mismatch at end of year (with the delta); `CorruptedYearState`,
  `QueryMismatch`, `TransientFailure`.

## Non-Goals (Explicit)

- No abstract OpenAlex client for arbitrary entities. Works only.
- No in-process parallelism. One cursor walk at a time.
- No caching layer. OpenAlex is the source of truth per run.
- No pluggable storage backend. Local disk only.
- No transformation of records. None added (`_extracted_at` is a downstream
  concern, sourced from `_META.json.started_at`), none dropped, no schema
  validation. Validate downstream in dbt staging.
- No repair of corrupted directories. The user owns filesystem hygiene.
- No concurrent runs against the same directory. No lockfile.

## Status

Stages 1 and 2 are closed. Stage 3 produces concrete signatures, type hints,
and docstrings — tight enough to write tests against and straightforward for
a coding agent to implement.
