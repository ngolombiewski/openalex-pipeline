"""Manual CLI entry point: ``python -m openalex_pipeline.extraction``.

Reads configuration from environment variables (and ``.env`` in the working
directory), runs the extraction, and prints a one-screen summary.

Exit codes:
  0 -- run completed, or stopped cleanly on the daily-limit (429). Both are
       expected outcomes; resume next day for the latter.
  1 -- connector or storage failure (RetryExhausted, NonRetryableError,
       QueryMismatch, CorruptedState).
  2 -- configuration error (missing/invalid env var).
"""

from __future__ import annotations

import sys

from loguru import logger
from pydantic import ValidationError

from . import runner
from .exceptions import ConnectorError, StorageError
from .models import RunReport
from .settings import Settings


def _configure_logging() -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    )
    logger.enable("openalex_pipeline.extraction")


def _print_report(report: RunReport) -> None:
    completed = sum(1 for o in report.outcomes if o.status == "completed")
    skipped = sum(1 for o in report.outcomes if o.status == "skipped")
    mismatches = [o for o in report.outcomes if o.report.count_mismatch]

    print(f"status: {report.status}")
    if report.stopped_year is not None:
        print(f"stopped at year: {report.stopped_year}")
    print(
        f"years processed: {len(report.outcomes)} "
        f"({completed} completed this run, {skipped} skipped as already complete)"
    )
    if mismatches:
        print(f"count mismatches in {len(mismatches)} year(s):")
        for o in mismatches:
            print(
                f"  {o.year}: expected={o.report.expected_count} "
                f"fetched={o.report.records_fetched}"
            )


def main() -> int:
    _configure_logging()
    try:
        settings = Settings()  # type: ignore[call-arg]
    except ValidationError as exc:
        print(f"configuration error:\n{exc}", file=sys.stderr)
        return 2

    try:
        report = runner.run(settings)
    except (ConnectorError, StorageError) as exc:
        print(f"extraction failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    _print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
