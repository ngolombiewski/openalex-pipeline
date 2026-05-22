"""Runner: builds canonical queries, loops years, aggregates the run report.

The runner is pure orchestration -- no disk I/O of its own. It reads the
configured filter and year range from a ``Settings`` instance, builds the
canonical query string for each year, calls ``worker.process_year`` for every
year, and aggregates the ``YearOutcome`` results into a fresh ``RunReport``.

``DailyLimitReached`` is the one exception the runner catches: it's an
expected daily stop, so the runner stops iterating, records the year where the
stop happened, and returns a partial report with ``status="stopped_daily_limit"``.
All other exceptions (``QueryMismatch``, ``CorruptedState``, ``RetryExhausted``,
``NonRetryableError``) propagate untouched.

Canonical query shape (with the year-specific filter appended)::

    works?filter={settings.filter},publication_year:{year}
    &select={SELECT_COLUMNS}&per_page={PER_PAGE}

Parameter and filter order are owned by this module; the connector may append
``cursor`` and the API-key parameter in any order without affecting query
identity.
"""

from __future__ import annotations

from . import connector, worker
from .exceptions import DailyLimitReached
from .models import RunReport, YearOutcome
from .settings import Settings

# Bronze source columns, pinned in docs/DATA_MODEL.md. The runner owns the
# order; any change must be reflected in the data model docs first.
SELECT_COLUMNS = (
    "id,title,publication_year,publication_date,type,language,is_retracted,"
    "is_paratext,primary_topic,topics,cited_by_count,counts_by_year,"
    "cited_by_percentile_year,citation_normalized_percentile,fwci,"
    "referenced_works_count,open_access,doi,ids,keywords,updated_date"
)
PER_PAGE = 200


def canonical_query(filter_str: str, year: int) -> str:
    """Build the canonical query string for one year.

    ``filter_str`` is the value of ``OPENALEX_FILTER`` (e.g.
    ``primary_topic.field.id:17``) -- the filter *expression* only; the
    ``filter=`` URL parameter name and the per-year ``publication_year``
    clause are appended here.

    Public so callers (and tests) can construct the same string the runner
    stores in ``_META.query``.
    """
    return (
        f"works?filter={filter_str},publication_year:{year}"
        f"&select={SELECT_COLUMNS}"
        f"&per_page={PER_PAGE}"
    )


def run(settings: Settings) -> RunReport:
    """Run the extraction over ``settings.years`` and return a RunReport.

    For each year (in ascending order), builds the canonical query and calls
    ``worker.process_year`` with ``connector.fetch_page``. A ``DailyLimitReached``
    raised by the worker terminates the loop cleanly and is reflected in the
    returned report; all other exceptions propagate.

    Returns:
        RunReport. ``status="complete"`` if every year was processed,
        ``status="stopped_daily_limit"`` with ``stopped_year`` set if a 429
        cut the run short.
    """
    outcomes: list[YearOutcome] = []
    for year in settings.years:
        query = canonical_query(settings.filter, year)
        try:
            outcome = worker.process_year(
                settings.data_dir,
                year,
                query,
                settings.api_key,
                connector.fetch_page,
            )
        except DailyLimitReached:
            return RunReport(
                outcomes=outcomes,
                status="stopped_daily_limit",
                stopped_year=year,
            )
        outcomes.append(outcome)
    return RunReport(outcomes=outcomes, status="complete")
