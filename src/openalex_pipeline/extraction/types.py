"""Value types passed between extraction-module functions.

All types here are frozen dataclasses (immutable value objects). They carry
data; they do not have behavior. Methods, if any, are pure derivations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class YearMeta:
    """Contents of a year directory's _META.json file.

    Written once on the first successful page fetch of a year; immutable
    thereafter. Records the target the year is being fetched against.

    Attributes:
        filter: the filter string used for this year's pull (without the
            "filter=" prefix). Used for M8 filter scope validation.
        expected_count: meta.count from the API's first response. Used for
            M6 drift detection at resume and M7 reconciliation at year end.
        started_at: timestamp of the first successful page fetch, UTC.
    """

    filter: str
    expected_count: int
    started_at: datetime


@dataclass(frozen=True)
class Page:
    """A single page of API results, as returned by request_page().

    Attributes:
        records: the list of work dicts as returned by OpenAlex. Records
            do NOT yet have the _extracted_at stamp (M9); that is injected
            by storage.write_page() at write time.
        meta_count: the meta.count value from the response. Used for both
            populating YearMeta.expected_count on the first page and for
            M6 drift detection on resume.
        next_cursor: the cursor for the next page, or None if this is the
            last page of the result set.
    """

    records: list[dict]
    meta_count: int
    next_cursor: str | None


@dataclass(frozen=True)
class ResumeTarget:
    """Where the runner should pick up its work for the next year to process.

    Used both for fresh starts and for resumes:
    - Fresh start: next_page_number=1, next_cursor="*", existing_meta=None.
    - Resume: next_page_number=(existing pages + 1), next_cursor=contents
        of _CURSOR, existing_meta=parsed _META.json.

    Attributes:
        year: the publication year to process next.
        next_page_number: 1-indexed page number to assign to the next page
            written. For a fresh year, this is 1.
        next_cursor: the cursor value to send to the API. "*" for fresh
            starts; the contents of _CURSOR when resuming.
        existing_meta: the YearMeta loaded from _META.json if resuming, or
            None if starting fresh. When non-None, the runner performs the
            M6 drift check against existing_meta.expected_count on the
            first response.
    """

    year: int
    next_page_number: int
    next_cursor: str
    existing_meta: YearMeta | None


@dataclass(frozen=True)
class ResumePlan:
    """Output of scan(). Tells the runner where to start and what to skip.

    Attributes:
        target: the year to resume or start, or None if everything in the
            current run's year range is already complete.
        completed_years: years with valid _SUCCESS whose filter has been
            verified to match the current run's filter (M8). The runner
            skips these.
    """

    target: ResumeTarget | None
    completed_years: frozenset[int]


@dataclass(frozen=True)
class YearOutcome:
    """Per-year result, accumulated into RunSummary.

    Attributes:
        year: the publication year.
        status: one of:
            - "complete": year fully fetched and _SUCCESS written this run.
            - "skipped_complete": year was already complete on entry.
            - "in_progress": year was being worked on when the run stopped
                (typically on credit exhaustion).
            - "drifted_restarted": year hit M6 drift, was discarded, and
                restarted successfully within the same run.
        pages_fetched: number of pages fetched from the API for this year
            during this run (excludes pages already on disk at resume).
        records_fetched: number of records fetched during this run.
    """

    year: int
    status: str
    pages_fetched: int
    records_fetched: int


@dataclass(frozen=True)
class RunSummary:
    """Aggregate result of a runner.run() invocation.

    Attributes:
        years: per-year outcomes in processing order.
        stopped_reason: one of:
            - "all_complete": every year in scope finished cleanly.
            - "credits_exhausted": ran out of daily API credits; resume tomorrow.
            - "error": uncaught error propagated; details in logs.
        total_records_fetched: sum across all years processed this run.
    """

    years: list[YearOutcome]
    stopped_reason: str
    total_records_fetched: int
