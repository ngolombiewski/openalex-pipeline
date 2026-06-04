# Bronze Ingestion — Test Design

Test plan for step 2 of the bronze build sequence. Tests are authored against
the **final module paths** (`src/openalex_pipeline/bronze/{core,manifest,runner,
__main__}.py`) and will be **red until step 3** (implementation). That is
intentional.

This doc is the deliverable to review **before** any test code is written. It
pins the fixture API, maps every contract surface to a test file and cases, and
calls out the contract gaps the test design exposed (see *Contract gaps* — these
need a decision before the tests can assert anything concrete).

Sources: `src/openalex_pipeline/bronze/contracts.py` (binding contracts),
`docs/bronze-design.md` (binding invariants + schema), real extraction output
under `data/extract/{year}/` (report shape).

---

## 1. Approach

- **Real Polars, real tmp filesystem.** No mocking of `pl.scan_ndjson`, no
  in-memory FS fakes. The point of the spike was to pin Polars' actual behavior;
  the tests exercise it. Bronze has no network surface, so nothing to mock.
- **One test file per source file**, matching the module layout's test seams:
  `test_core.py`, `test_manifest.py`, `test_runner.py`, `test_main.py`.
- **Tests import from final paths**, never from `contracts.py` (which is deleted
  at the start of step 3). E.g. `from openalex_pipeline.bronze.core import
  classify_year, YearState`.
- **Behavior over implementation.** Where a contract leaves a representation
  detail open (e.g. the dtype of `ingested_at`), tests assert the observable
  property (stability across reruns) rather than a concrete dtype, and the
  ambiguity is flagged in *Contract gaps*.

Test tree:

```
tests/bronze/
  __init__.py
  conftest.py        # fixtures + builders (section 2)
  test_core.py
  test_manifest.py
  test_runner.py
  test_main.py
```

---

## 2. Fixture strategy

The natural fixture is a tmp directory laid out like real extraction output:
numeric year subdirs, each with `_YEAR_REPORT.json` and `page-*.jsonl` files.
The whole builder surface lives in `tests/bronze/conftest.py`.

### 2.1 Path fixtures

```python
@pytest.fixture
def extract_root(tmp_path) -> Path     # tmp_path / "extract", created
@pytest.fixture
def bronze_root(tmp_path) -> Path      # tmp_path / "bronze", created
```

Both are passed explicitly to every function under test, so no env var or CWD
coupling. (`__main__` env/flag resolution is tested separately with monkeypatch.)

### 2.2 Record builder

```python
def make_record(id_="W1", **overrides) -> dict
```

Returns one OpenAlex-shaped record with **all 21 schema keys** present and
type-correct under `BRONZE_SCHEMA`:

- scalars: `id` (str), `title` (str), `publication_year` (int), `type`,
  `language`, `is_retracted`/`is_paratext` (bool), `cited_by_count` (int),
  `fwci` (float), `referenced_works_count` (int), `doi`,
  `publication_date`/`updated_date` (str).
- the eight **nested** fields (`primary_topic`, `topics`, `counts_by_year`,
  `cited_by_percentile_year`, `citation_normalized_percentile`, `open_access`,
  `ids`, `keywords`) as **real dict/list objects** — so they serialize to nested
  JSON in the JSONL, and bronze's forced-String read lands them as raw JSON
  strings. This is what lets us assert the forced-String *fidelity* property
  (missing keys not fabricated).

`overrides` replaces any field, including with intentionally wrong-typed values
(`make_record(cited_by_count="lots")`) or `id_=None` for the integrity test.
Passing `field=_OMIT` (a sentinel) drops the key entirely, to exercise a record
that omits a nested key — needed for the no-key-fabrication test.

### 2.3 Extraction-year builder

```python
def make_extract_year(
    extract_root, year, *,
    records=None,            # list[dict]; default [make_record("W1"), make_record("W2")]
    complete=True,           # write _YEAR_REPORT.json -> READY; else omit -> PENDING
    pages=None,              # optional list[list[dict]] to split records across page files
    empty=False,             # write a single zero-byte page-0001.jsonl (zero-result year)
    report=None,             # dict of _YEAR_REPORT overrides (query, expected_count,
                             #   records_fetched, count_mismatch, completed_at, ...)
    no_pages=False,          # write report but zero page files (corruption case)
) -> Path                    # the year dir
```

Behavior:

- Creates `{extract_root}/{year}/`.
- `empty=True`: writes one zero-byte `page-0001.jsonl`, no records.
- `pages` given: one `page-NNNN.jsonl` per sublist (multi-page years, page
  discovery/ordering coverage). Otherwise all `records` go to `page-0001.jsonl`.
- `complete=True`: writes `_YEAR_REPORT.json` with sensible defaults derived from
  the data (`records_fetched=len(records)`, `expected_count=len(records)`,
  `count_mismatch=False`, fixed `completed_at`, a realistic `query`), each
  overridable via `report`.
- `complete=False`: no report → the year is PENDING (covers "directory present
  but incomplete").
- `no_pages=True` with `complete=True`: report present, zero page files →
  the `CorruptedState` classification case.

A line-level corruption helper:

```python
def corrupt_page_line(page_path, line_no=0, text="{not valid json")  # overwrite one line
```

writes a syntactically broken JSON line into an existing page file, to exercise
the malformed-JSONL-on-disk read failure.

### 2.4 Read helpers

```python
def read_year_parquet(bronze_root, year) -> pl.DataFrame   # pl.read_parquet
def read_manifest(bronze_root) -> pl.DataFrame
def manifest_row(manifest, year) -> dict                   # the row for one year, as a dict
```

### 2.5 Time control

`ingested_at` derives from the Parquet's mtime, not wall-clock. Tests pin it
deterministically with `os.utime(parquet_path, (ts, ts))` and compare against the
file's own `stat().st_mtime`, so they never depend on the exact column dtype.
`freezegun` (already a dev dep) is available if a test needs a frozen "now", but
the mtime approach is preferred because it tests the actual contract.

---

## 3. Contract → test mapping

### 3.1 `test_core.py` — `classify_year`, `ingest_year`, `write_empty_year`

| # | Case | Asserts |
|---|---|---|
| C1 | parquet exists → INGESTED | `classify_year` returns `INGESTED`; even if extraction dir is absent or corrupt (existence-only check, no read). A garbage/empty `{year}.parquet` still classifies INGESTED. |
| C2 | report present, page files present, no parquet → READY | returns `READY`. |
| C3 | dir present, no report → PENDING | returns `PENDING`. |
| C4 | no extraction dir at all → PENDING | returns `PENDING`. |
| C5 | report present, **zero page files** → CorruptedState | `classify_year` raises `CorruptedState`. |
| C6 | C5 but parquet also exists → INGESTED | parquet check precedes the corruption check; no raise. |
| C7 | `ingest_year` READY happy path | writes `{year}.parquet`; result `state=READY`, `bronze_row_count=len(records)`, `duplicate_id_count=0`; `bronze_file_path` is the **absolute** path to the written file (G3); no `.tmp` left behind. |
| C8 | written parquet schema | read back: `schema == BRONZE_SCHEMA` (names, dtypes, **canonical order**). |
| C9 | forced-String fidelity | nested columns are `String` holding **valid JSON that equals the raw source object**; a record omitting a nested key does **not** gain a fabricated `null` key (the rejected struct-encode behavior). |
| C10 | multi-page year | records split across `page-0001..000N.jsonl` are all read in one pass; row count = total; page order respected. |
| C11 | duplicate id count | two rows share an `id` → `duplicate_id_count == 1` (`row_count - n_unique`); three copies of one id → 2; **non-blocking** (parquet still written, no raise). |
| C12 | null id → IntegrityError | a record with `id=None` → `ingest_year` raises `IntegrityError`; **no `{year}.parquet` and no `.tmp`** written (assertion precedes write). |
| C13 | scalar type mismatch → CorruptedState | a record with a wrong-typed scalar (e.g. `cited_by_count="lots"`) → `ingest_year` raises `CorruptedState` (Polars `ComputeError` wrapped, per G1); no parquet/tmp written. |
| C14 | malformed JSONL on disk → CorruptedState | `corrupt_page_line` then `ingest_year` → `CorruptedState`; no parquet/tmp written. |
| C15 | `ingest_year` on INGESTED year | returns immediately, `state=INGESTED`, `bronze_file_path` set, counts `None`; existing parquet **not** rewritten (mtime unchanged). |
| C16 | `ingest_year` on PENDING year | returns immediately, `state=PENDING`, counts and path `None`; nothing written. |
| C17 | zero-result year via `ingest_year` | single zero-byte page file → delegates to empty path; `{year}.parquet` exists, 0 rows, full schema. |
| C18 | `write_empty_year` directly | returns the path; file is an empty frame with `schema == BRONZE_SCHEMA`; 0 rows; atomic (no `.tmp` left). |
| C19 | disallowed zero-byte combos → CorruptedState | a zero-byte page alongside a non-empty page, and (separately) two zero-byte pages → `ingest_year` raises `CorruptedState` (G4); no parquet/tmp written. |
| C20 | row count != `records_fetched` → IntegrityError | a year whose page data has a different row count than its `_YEAR_REPORT.json` `records_fetched` → `ingest_year` raises `IntegrityError` (assertion precedes write); no parquet/tmp written. The loud bronze-vs-extraction count check. |

### 3.2 `test_manifest.py` — `build_manifest`, `write_manifest`

| # | Case | Asserts |
|---|---|---|
| M1 | one row per requested year | `build_manifest(..., years=[a,b,c])` → exactly 3 rows, keyed by `publication_year`, regardless of what else is on disk. |
| M2 | INGESTED row fully populated | for an ingested year: `status="ingested"`; extraction fields (`query`, `expected_count`, `records_fetched`, `count_mismatch`, `extraction_completed_at`) forwarded verbatim from `_YEAR_REPORT.json`; `bronze_row_count` = actual parquet rows; `duplicate_id_count` from parquet; `bronze_file_path` set; `ingested_at` set. |
| M3 | PENDING row (no report) | bronze-side cols (`bronze_row_count`, `duplicate_id_count`, `bronze_file_path`, `ingested_at`) **and** extraction-side cols null; `status="pending"`. |
| M4 | READY row representable | a READY-but-not-ingested year at build time → `status="ready"`, extraction cols populated, bronze cols null. *(Confirms the three-state status; see Gap G2.)* |
| M5 | `count_mismatch` forwarded verbatim | report `count_mismatch=True` → manifest `count_mismatch=True` (non-blocking; no raise anywhere). |
| M6 | `bronze_row_count` == `records_fetched` for an INGESTED year | the two are equal by construction (the divergence case is a loud `IntegrityError` at ingestion — see C20 — so it can never reach a written Parquet); the manifest records both for visibility. `build_manifest` does **not** re-check or raise. |
| M7 | `ingested_at` derives from mtime | `os.utime` the parquet to a fixed past time → `build_manifest` → `ingested_at` reflects that mtime, **not** "now". |
| M8 | `ingested_at` stable across rebuilds | build manifest twice without touching the parquet → identical `ingested_at` both times (the "never re-stamp" property). |
| M9 | `bronze_file_path` value | manifest column is **relative to bronze_root** — the string `"{year}.parquet"` (G3; contrast C7's absolute `YearIngestResult` path). |
| M10 | `write_manifest` | writes `{bronze_root}/_MANIFEST.parquet`; returns the path; readable as parquet; round-trips M1's row set; no `.tmp` left; a second `write_manifest` overwrites wholesale. |

### 3.3 `test_runner.py` — `run`

| # | Case | Asserts |
|---|---|---|
| R1 | ingest a range | `run(..., years=[y1,y2])` with both READY → both `{year}.parquet` written; `_MANIFEST.parquet` written; returns a manifest DataFrame with exactly those 2 rows. |
| R2 | mixed states | years = one READY, one already-INGESTED, one PENDING → only the READY one is written this run; manifest has all three with correct statuses. |
| R3 | manifest scoped to `years` | on-disk has extra ingested years outside `years` → they do **not** appear in the manifest (range scopes the manifest, Invariant 6). |
| R4 | idempotent rerun | run twice with same `years`; second run reclassifies done years INGESTED and skips them: parquet mtimes unchanged, `ingested_at` unchanged between the two returned manifests. |
| R5 | catch-up | run #1 over `[y1,y2]` with only `y1` READY (`y2` PENDING); then `y2` becomes READY; run #2 over same range ingests `y2`, leaves `y1` untouched (same operation as a range ingest — Invariant: catch-up == range). |
| R6 | IntegrityError propagates | a READY year with a null id → `run` raises `IntegrityError`; run stops (fails loud). |
| R7 | CorruptedState propagates | a READY year with malformed JSONL → `run` raises `CorruptedState`. |
| R8 | return value == written manifest | the returned DataFrame equals what `read_manifest` reads back from disk. |

### 3.4 `test_main.py` — `parse_args`, `resolve_roots`, `build_years_list`, `main`

| # | Case | Asserts |
|---|---|---|
| A1 | `parse_args` | parses `--extract-root`, `--bronze-root`, `--years`; `--years` default `None`. |
| A2 | `resolve_roots` flags win | explicit flags → those paths, env ignored. |
| A3 | `resolve_roots` env default | no flags, `OPENALEX_DATA_ROOT=X` set (monkeypatch) → `(X/extract, X/bronze)`. |
| A4 | `resolve_roots` missing config | no flag and no env → `SystemExit`. |
| A5 | `resolve_roots` extract_root absent | resolved extract_root does not exist → `SystemExit`. |
| A6 | `build_years_list` explicit range | `"1953:1955"` → `[1953,1954,1955]` (inclusive). |
| A7 | explicit-range PENDING semantics | range covers years with **no extraction dir at all** → they are still in the list and classify PENDING downstream. (The range is the universe.) |
| A8 | `build_years_list` discover mode | `years_arg=None` → every numeric subdir, sorted; non-numeric dirs and files ignored. |
| A9 | discover PENDING semantics | a numeric dir present-but-incomplete appears (→ PENDING); a year with **no** dir does **not** appear. (Contrast with A7 — the one place the modes diverge.) |
| A10 | `build_years_list` errors | malformed `--years` (`"abc"`, `"1950:"`, `"1950:1940"` with START>END) → `SystemExit`; discover mode with no numeric subdirs → `SystemExit`. |
| A11 | `main` explicit range end-to-end | `main(["--extract-root", ..., "--bronze-root", ..., "--years", "1953:1954"])` → parquet(s) + manifest written; prints per-year summary. |
| A12 | `main` discover end-to-end | `main([... no --years])` → ingests discovered READY years. |
| A13 | `main` surfaces warnings | a year with non-zero `duplicate_id_count` and a year with `count_mismatch=True` → both surfaced as human-visible warnings in stdout (the "smoke alarm"), run still succeeds. |
| A14 | `main` does not swallow BronzeError | a corrupt/integrity-failing year → `BronzeError` subclass propagates out of `main` (not caught). |

---

## 4. Required-coverage cross-checks

These are the load-bearing properties the prompt calls out explicitly. Each maps
to at least one case above; this table is the audit that none slipped.

### 4.1 Integrity assertions & corruption modes (design §Integrity, Invariants)

| Invariant / check | Mode | Test(s) |
|---|---|---|
| Non-null `id` | loud | C12, R6 |
| `bronze_row_count` == `records_fetched` | loud | C20 (and M6 confirms equality holds post-write) |
| Scalar type conformance (read-time) | loud | C13 |
| Duplicate `id` count | non-blocking | C11, M6, A13 |
| `count_mismatch` forwarded | non-blocking | M5, A13 |
| Malformed JSONL on disk | loud | C14, R7 |
| Report present + zero page files | loud | C5 (and C6 precedence) |
| Atomic write (no partial/`.tmp` survives; failures write nothing) | — | C7, C12, C14, C18, M10 |
| Output-Parquet-presence = completion (existence-only classify) | — | C1, C6 |
| Explicit schema, no inference (21 cols, nested = String) | — | C8, C9, C17, C18 |

### 4.2 `__main__` invocation modes & PENDING semantics

The two modes differ **only** in how `years` is built, and that difference is
precisely their PENDING coverage:

- **Explicit range** — the range is the universe; a year with no extraction dir
  is in-list and PENDING. → A6, A7, A11.
- **Discover** — existing numeric subdirs are the universe; missing-dir years are
  absent entirely, present-incomplete years are PENDING. → A8, A9, A12.

### 4.3 Manifest "rebuilt wholesale, never authoritative"

- Rebuilt wholesale / scoped to `years`, not the whole dir: M1, R3.
- Overwrites, never appends: M10.
- **Never re-stamps `ingested_at`** (uses Parquet mtime, not "now"): M7 (derives
  from mtime), M8 (stable across rebuild), R4 (stable across full rerun, parquet
  not rewritten).

---

## 5. Contract gaps / ambiguities — RESOLVED

The test design surfaced four points; all four are now decided and the
resolutions are reflected in `contracts.py` and the case tables above.

**G1 — scalar type mismatch → `CorruptedState`.** Polars' `ComputeError` is
wrapped uniformly as `CorruptedState`, identical to malformed JSONL: all
read-time failures share one loud bronze-typed exception. `contracts.py`
(`CorruptedState`, `ingest_year` `Raises:`) updated. → C13.

**G2 — three states.** `status` ∈ {`ingested`, `ready`, `pending`}. In prod a
manifest is only built after all READY years are ingested, so `ready` is rare,
but `build_manifest` called in isolation (as tests do) can produce it, so it is
representable. → M4.

**G3 — real inconsistency, pinned as two distinct fields.** The manifest column
`bronze_file_path` is **relative to bronze_root** (`"{year}.parquet}"`) — "where
to find files relative to the manifest". `YearIngestResult.bronze_file_path` is
the **absolute** filesystem path — "I just wrote/found this file, here it is" for
a mid-run caller. Same name, two jobs, two consumers. Documented explicitly in
both docstrings in `contracts.py`. → C7 (absolute), M9 (relative).

**G4 — contract tightened.** Only "exactly one zero-byte `page-0001.jsonl`" is a
valid zero-result year. Any other zero-byte combination (zero-byte page among
non-empty pages, multiple zero-byte pages) is not a state extraction can produce
and raises `CorruptedState`. `ingest_year` step 2 + `Raises:` updated. → C19.

**Minor Q2 — schema equality is exact and ordered** (C8, C18). **Minor Q3 —
`main`'s warnings go through `loguru`**, not bare stdout; A13 captures loguru
output (see §3.4 note).

---

## 6. Notes carried into authoring

- **loguru capture (A13/A11/A12).** `main` emits its per-year summary and the
  non-zero `duplicate_id_count` / `count_mismatch` warnings through loguru. Tests
  capture via a `loguru` sink added in a fixture (`caplog` does not see loguru by
  default). The conftest provides a `loguru_messages` fixture that adds a sink to
  a list and removes it on teardown.
- **Red until step 3.** Every test imports from the final module paths
  (`core`, `manifest`, `runner`, `__main__`), which do not exist yet. Collection
  will fail / tests will error until implementation lands — expected and correct.

---

**Next step:** author the four test files + `conftest.py` exactly as mapped
above.
