"""Bronze ingestion exceptions.

A leaf module. Two leaves: a base class so callers can catch by category, and
two failure leaves mirroring the extraction module's two-base-class scheme.
"""

from __future__ import annotations


class BronzeError(Exception):
    """Base for all bronze ingestion failures.

    Lets __main__ and any future orchestrator catch by category without
    enumerating leaves.
    """


class CorruptedState(BronzeError):
    """A year is in a file combination bronze cannot interpret.

    Raised by classify_year / ingest_year. Cases:
      - An extraction year directory has _YEAR_REPORT.json present but zero
        page-*.jsonl files (impossible under a correct extraction run).
      - Malformed JSONL surfaced by the Polars read.
      - A scalar value that does not conform to its BRONZE_SCHEMA dtype: Polars
        raises ComputeError on read, which bronze wraps as CorruptedState so
        every read-time failure surfaces as one loud, bronze-typed exception.
      - Any zero-byte page-file combination other than the single zero-byte
        page-0001.jsonl that denotes a zero-result year.

    Corruption is loud: there is no silent recovery.
    """


class IntegrityError(BronzeError):
    """A bronze integrity assertion failed during ingestion.

    Two assertions, both over a READY year's freshly read frame, before write:
      - Non-null `id` (record-level).
      - bronze_row_count == records_fetched (aggregate): the Parquet row count
        must equal extraction's asserted line count. Duplicates count equally on
        both sides, so a divergence means bronze lost/multiplied rows or a page
        was truncated on disk -- a defect, not source churn.

    On failure the year's Parquet is not written, so a re-run re-attempts the
    year cleanly.
    """
