"""Value types shared across the extraction module."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Literal


class YearState(Enum):
    """The three valid states of a year shard directory.

    There is intentionally no fourth value for the "finalize-pending"
    sub-state (last page written, ``_YEAR_REPORT.json`` not yet written). That
    sub-state is just ``IN_PROGRESS`` with ``cursor is None``; the worker infers
    it and skips straight to ``finalize_year``. A fourth enum value would only
    tempt a fourth code path.
    """

    FRESH = auto()
    IN_PROGRESS = auto()
    COMPLETE = auto()


@dataclass(frozen=True)
class YearStatus:
    """Result of ``classify_year``.

    For ``FRESH`` and ``COMPLETE``, ``cursor`` and ``next_page`` are ``None``
    and must not be read. For ``IN_PROGRESS`` they carry the resume pointer
    read from ``_CURSOR.json``:

      - ``cursor``    -- OpenAlex token for the next page to fetch. May itself
                         be ``None``, which is the finalize-pending sub-state
                         (all pages fetched, ``finalize_year`` still owed).
      - ``next_page`` -- 1-based page number ``cursor`` points to; the worker's
                         starting induction value.
    """

    state: YearState
    cursor: str | None = None
    next_page: int | None = None


@dataclass(frozen=True)
class YearReport:
    """Durable completion report written to ``_YEAR_REPORT.json``."""

    query: str
    year: int
    started_at: str
    completed_at: str
    expected_count: int
    records_fetched: int
    page_count: int
    count_mismatch: bool


@dataclass(frozen=True)
class YearOutcome:
    """In-memory outcome for one year in the current invocation."""

    year: int
    status: Literal["completed", "skipped"]
    report: YearReport


@dataclass(frozen=True)
class RunReport:
    """In-memory report for one runner invocation."""

    outcomes: list[YearOutcome]
    status: Literal["complete", "stopped_daily_limit"]
    stopped_year: int | None = None
