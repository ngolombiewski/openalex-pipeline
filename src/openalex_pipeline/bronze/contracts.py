"""Bronze ingestion — contracts.

JSONL -> Parquet materialization for the OpenAlex CS corpus. One Parquet file
per calendar-year shard. Bronze is a thin format conversion: an explicit schema
is imposed on read, nested fields are landed as raw JSON strings, and no
flattening, dedup, or consistency checking is done beyond the integrity
assertions below.

Settled design: see docs/bronze-ingestion-design.md. The schema, invariants,
and contracts in this file are binding; this file is the input for the
test-writing step. Function bodies are intentionally unimplemented (`...`).

Build sequence (mirrors the extraction module):
    1. Contracts — this file.
    2. Design + write tests against the contracts.
    3. Implement.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import polars as pl


# --- Schema -----------------------------------------------------------------

BRONZE_SCHEMA: dict[str, pl.DataType] = {
    "id": pl.String,
    "title": pl.String,
    "publication_year": pl.Int64,
    "publication_date": pl.String,
    "type": pl.String,
    "language": pl.String,
    "is_retracted": pl.Boolean,
    "is_paratext": pl.Boolean,
    "primary_topic": pl.String,
    "topics": pl.String,
    "cited_by_count": pl.Int64,
    "counts_by_year": pl.String,
    "cited_by_percentile_year": pl.String,
    "citation_normalized_percentile": pl.String,
    "fwci": pl.Float64,
    "referenced_works_count": pl.Int64,
    "open_access": pl.String,
    "doi": pl.String,
    "ids": pl.String,
    "keywords": pl.String,
    "updated_date": pl.String,
}
"""The 21-column bronze schema. Imposed on read; no schema inference is used.

Column order is the canonical bronze column order. The eight nested columns
(primary_topic, topics, counts_by_year, cited_by_percentile_year,
citation_normalized_percentile, open_access, ids, keywords) are pl.String
holding raw verbatim JSON, exactly as OpenAlex emitted it. They are parsed
downstream in dbt staging, not here.

The scalar dtypes are load-bearing for integrity: a scalar whose value does not
conform to its dtype raises a Polars ComputeError on read (verified by spike).
Scalar type-conformance is therefore a read-time invariant, not a separate
check (see Invariant 4 in the design doc).

publication_date and updated_date are deliberately pl.String, not pl.Date:
date typing is deferred to dbt staging, consistent with bronze staying thin and
with avoiding a malformed-date-fails-read failure mode.
"""

NESTED_COLUMNS: tuple[str, ...] = (
    "primary_topic",
    "topics",
    "counts_by_year",
    "cited_by_percentile_year",
    "citation_normalized_percentile",
    "open_access",
    "ids",
    "keywords",
)
"""The eight columns landed as raw JSON strings. Subset of BRONZE_SCHEMA keys."""


# --- Exceptions -------------------------------------------------------------

class BronzeError(Exception):
    """Base for all bronze ingestion failures.

    Lets __main__ and any future orchestrator catch by category without
    enumerating leaves. Mirrors the extraction module's two-base-class scheme.
    """


class CorruptedState(BronzeError):
    """A year is in a file combination bronze cannot interpret.

    Raised by classify_year / ingest_year. Cases:
      - An extraction year directory has _YEAR_REPORT.json present but zero
        page-*.jsonl files. The extraction contract guarantees >=1 page file
        for any non-fresh year, so this combination is impossible under a
        correct extraction run and is therefore corruption.
      - Malformed JSONL surfaced by the Polars read of a year claimed COMPLETE.

    Corruption is loud: there is no silent recovery. This mirrors the
    extraction module's stance.
    """


class IntegrityError(BronzeError):
    """A record-level integrity assertion failed during ingestion.

    Currently the only such assertion is non-null `id`. On failure the year's
    Parquet is not written, so a re-run re-attempts the year cleanly.
    """


# --- Year classification ----------------------------------------------------

class YearState(Enum):
    """The three states a requested year can be in.

    INGESTED  -- {bronze_root}/{year}.parquet already exists. Skip; never
                 re-read. An INGESTED year's extraction state is irrelevant.
    READY     -- extraction marked the year COMPLETE (_YEAR_REPORT.json present)
                 and no bronze Parquet exists yet. This year gets ingested.
    PENDING   -- extraction has not completed the year (directory absent, or
                 present but without _YEAR_REPORT.json). Skipped this run;
                 surfaced in the manifest so pipeline progress is visible.
    """

    INGESTED = "ingested"
    READY = "ready"
    PENDING = "pending"


def classify_year(extract_root: Path, bronze_root: Path, year: int) -> YearState:
    """Classify one year against the extraction and bronze directories.

    Decision order:
      1. If {bronze_root}/{year}.parquet exists            -> INGESTED.
      2. Else if {extract_root}/{year}/_YEAR_REPORT.json exists -> READY.
      3. Else                                              -> PENDING.

    The bronze Parquet is checked first by design: an INGESTED year is never
    re-read, so its extraction-side state does not matter. PENDING covers both
    "extraction year directory is present but incomplete" and "no extraction
    directory at all" -- the caller does not need to distinguish them.

    Raises:
        CorruptedState: the extraction year directory has _YEAR_REPORT.json
            but zero page-*.jsonl files (an impossible state under a correct
            extraction run; see CorruptedState).
    """
    ...


# --- Single-year ingestion --------------------------------------------------

@dataclass
class YearIngestResult:
    """In-memory outcome of handling one year.

    Not persisted. The runner collects these and build_manifest consumes the
    directory state directly, so YearIngestResult is a per-invocation report
    object, not durable state.

    bronze_row_count and duplicate_id_count are populated only when the year
    was freshly ingested this run (state READY -> written). For INGESTED and
    PENDING years they are None -- their values, if wanted, come from reading
    the existing Parquet during build_manifest.

    bronze_file_path is set for INGESTED years and for freshly written years;
    None for PENDING.
    """

    year: int
    state: YearState
    bronze_row_count: int | None = None
    duplicate_id_count: int | None = None
    bronze_file_path: Path | None = None


def ingest_year(extract_root: Path, bronze_root: Path, year: int) -> YearIngestResult:
    """Ingest one year to {bronze_root}/{year}.parquet.

    For a READY year:
      1. Discover page-*.jsonl files for the year.
      2. If the only page file is zero bytes (zero-result extraction year),
         delegate to write_empty_year and return.
      3. Otherwise read all page files in a single pass under BRONZE_SCHEMA.
      4. Assert the non-null `id` invariant over the frame.
      5. Count duplicate ids (see below).
      6. Write {year}.parquet atomically: write {year}.parquet.tmp, then
         rename into place. A file that exists is therefore necessarily
         complete.

    For an INGESTED year: return immediately, no read, no write. The result
    carries state=INGESTED and bronze_file_path; counts are None.

    For a PENDING year: return immediately, nothing written. The result
    carries state=PENDING; counts and path are None.

    duplicate_id_count semantics: excess rows beyond unique ids, computed as
    row_count - id.n_unique(). One id appearing three times contributes 2.
    This is "how many rows a dedup would remove", not "how many distinct ids
    are duplicated". It is recorded in the manifest and is NON-BLOCKING -- a
    non-zero value never fails the run (a duplicate can be source-side churn,
    not corruption; see the design doc).

    Zero-result year: written as an empty Parquet typed by BRONZE_SCHEMA via
    write_empty_year. A downstream scan of that file behaves like any other
    year. (scan_ndjson fails on a zero-byte file, so the empty case is
    detected and handled before any read.)

    Raises:
        IntegrityError: a record has a null `id`. The Parquet is not written.
        CorruptedState: classification ambiguity (see classify_year), or
            malformed JSONL on disk surfaced by the Polars read. Bronze does
            not independently re-validate JSON well-formedness -- every line
            was valid JSON at extraction write time -- but a malformed line
            from post-write disk corruption fails the read loudly, which is
            the desired behavior.

    Note: bronze does NOT re-validate extraction's report-level integrity
    (line counts, page contiguity, count_mismatch). It trusts extraction
    within extraction's own scope. The only record-level assertion is
    non-null `id`.
    """
    ...


def write_empty_year(bronze_root: Path, year: int) -> Path:
    """Write an empty {year}.parquet carrying the full 21-column BRONZE_SCHEMA.

    Used for a zero-result extraction year (a single zero-byte page file).
    The output is an empty DataFrame typed by BRONZE_SCHEMA, so a downstream
    scan sees the correct columns and dtypes and behaves like any non-empty
    year. Atomic (tmp + rename). Returns the written path.

    Public (rather than an internal helper of ingest_year) so tests can
    exercise the empty-year path directly.
    """
    ...


# --- Manifest ---------------------------------------------------------------

def build_manifest(extract_root: Path, bronze_root: Path, years: list[int]) -> pl.DataFrame:
    """Build the manifest DataFrame: one row per year in `years`.

    The manifest is DERIVED and NEVER AUTHORITATIVE: it is rebuilt wholesale
    every run from on-disk state and cannot desync from the Parquet files.
    The per-year Parquet's existence -- not the manifest -- is the
    authoritative completion signal.

    For each year, classify it, then populate:

      publication_year        -- the year (row key).
      status                  -- the YearState value: "ingested" / "ready" /
                                  "pending". (A year still READY at manifest
                                  build time was not ingested this run; rare,
                                  but representable.)
      query                   -- from extraction _YEAR_REPORT.json.
      expected_count          -- from extraction _YEAR_REPORT.json
                                  (OpenAlex meta.count at extraction time).
      records_fetched         -- from extraction _YEAR_REPORT.json.
      count_mismatch          -- from extraction _YEAR_REPORT.json; forwarded
                                  verbatim. NON-BLOCKING -- a count-mismatched
                                  year is not a bronze failure.
      extraction_completed_at -- from extraction _YEAR_REPORT.json.
      bronze_row_count        -- actual row count of {year}.parquet. Compared
                                  against records_fetched, this is bronze's
                                  own count check: a difference means bronze
                                  lost or duplicated rows (a bronze bug),
                                  distinct from extraction's count_mismatch.
      duplicate_id_count      -- excess rows beyond unique ids in the Parquet.
      bronze_file_path        -- relative path to {year}.parquet.
      ingested_at             -- the mtime of {year}.parquet. Using the file's
                                  mtime (not "now") keeps the timestamp stable
                                  across manifest rebuilds: a re-run does not
                                  re-stamp an already-ingested year.

    Bronze-side columns (bronze_row_count, duplicate_id_count,
    bronze_file_path, ingested_at) are null for PENDING years. Extraction-side
    columns are null for a PENDING year that has no _YEAR_REPORT.json yet.
    """
    ...


def write_manifest(bronze_root: Path, manifest: pl.DataFrame) -> Path:
    """Write the manifest to {bronze_root}/_MANIFEST.parquet.

    Atomic (tmp + rename). Overwrites any existing manifest wholesale.
    Returns the written path.
    """
    ...


# --- Runner -----------------------------------------------------------------

def run(extract_root: Path, bronze_root: Path, years: list[int]) -> pl.DataFrame:
    """Ingest every READY year in `years`, then rebuild and write the manifest.

    Steps:
      1. For each year in `years`: classify and, if READY, ingest_year.
         INGESTED and PENDING years are skipped. CorruptedState and
         IntegrityError propagate -- bronze fails loud and the run stops.
      2. After the loop: build_manifest over the full `years` list and
         write_manifest.
      3. Return the manifest DataFrame.

    `years` scopes ingestion AND the manifest: the manifest contains exactly
    one row per year in `years`, no more. The two invocation modes differ only
    in how `years` is constructed upstream (see build_years_list).

    Idempotent: re-running with the same `years` re-classifies already-done
    years as INGESTED and skips them cheaply. "Ingest a range" and "catch up
    on newly completed years" are therefore the same operation.
    """
    ...


# --- CLI entrypoint (__main__.py) -------------------------------------------
#
# The module is invoked as `python -m bronze`. __main__.py is intentionally
# thin: parse args, build the years list, call run(), print a summary. It
# contains no classification or ingestion logic -- those belong to run() and
# classify_year(). No Settings object: bronze has no secrets and no env
# config beyond a single root path, so plain argparse + one env var default
# is sufficient (unlike the extraction module, which needs Pydantic
# BaseSettings for its API key and query params).

OPENALEX_DATA_ROOT_ENV = "OPENALEX_DATA_ROOT"
"""Env var naming the project data root. Both pipeline modules derive their
directories from it: extraction uses {root}/extract, bronze uses
{root}/bronze and reads {root}/extract. This is a deliberate, stated coupling
-- bronze depends on extraction's "/extract" layout convention. The env var
is a DEFAULT only; the --extract-root / --bronze-root CLI flags override it
(which is also how tests inject tmp paths without touching the environment).
"""


def resolve_roots(
    args: argparse.Namespace,
) -> tuple[Path, Path]:
    """Resolve (extract_root, bronze_root) from CLI args and the environment.

    Precedence for each root:
      1. The explicit --extract-root / --bronze-root flag, if given.
      2. Else {OPENALEX_DATA_ROOT}/extract and {OPENALEX_DATA_ROOT}/bronze.

    Raises:
        SystemExit: neither the relevant flag nor OPENALEX_DATA_ROOT is set,
            or extract_root does not exist.
    """
    ...


def build_years_list(extract_root: Path, years_arg: str | None) -> list[int]:
    """Construct the list of years to process.

    Two modes:

      Explicit range -- `years_arg` is a "START:END" string (e.g. "1950:2004").
        Parsed into the inclusive integer range [START, END]. The range is the
        universe: every year in it is processed, and any year in it that
        extraction has not completed is classified PENDING (including years
        with no extraction directory at all).

      Default (discover) -- `years_arg` is None. Scan extract_root for every
        numeric subdirectory and return those years sorted. The set of
        existing extraction year directories is the universe. Complete
        directories classify as READY/INGESTED; incomplete ones (e.g. a year
        extraction is mid-pull on) classify as PENDING. Years extraction has
        not yet started have no directory and so do not appear at all -- this
        is intentional: a pure scan cannot know the corpus range, and bronze
        deliberately hardcodes no corpus bounds.

    The two modes give the manifest different coverage by design: a bounded
    question under an explicit range, a "whatever exists" snapshot under the
    default. This is the one place the invocation modes genuinely diverge.

    Raises:
        SystemExit: `years_arg` is malformed, or START > END, or the default
            scan finds no numeric subdirectories in extract_root.
    """
    ...


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments.

    Arguments:
      --extract-root PATH  Override the extraction input directory. Default:
                           {OPENALEX_DATA_ROOT}/extract.
      --bronze-root PATH   Override the bronze output directory. Default:
                           {OPENALEX_DATA_ROOT}/bronze.
      --years START:END    Inclusive year range to ingest. If omitted, bronze
                           discovers and ingests every extraction-complete
                           year found under extract_root.
    """
    ...


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint.

    Flow: parse_args -> resolve_roots -> build_years_list -> run -> print a
    per-year summary from the returned manifest, surfacing non-zero
    duplicate_id_count and count_mismatch as human-visible warnings (the
    "smoke alarm" role -- non-blocking, but not silent).

    BronzeError subclasses propagate as loud failures; main does not swallow
    them.
    """
    ...


if __name__ == "__main__":
    main()
