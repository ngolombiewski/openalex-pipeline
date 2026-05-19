from __future__ import annotations

import pytest

from openalex_pipeline.extraction.config import Settings
from openalex_pipeline.extraction.errors import CorruptedYearState, FilterScopeMismatch
from openalex_pipeline.extraction.scan import scan

from .conftest import write_cursor, write_meta, write_page_file, write_success, year_dir


def test_scan_returns_first_untouched_year_as_fresh_target(settings: Settings) -> None:
    plan = scan(settings)

    assert plan.target is not None
    assert plan.target.year == 1980
    assert plan.target.next_page_number == 1
    assert plan.target.next_cursor == "*"
    assert plan.target.existing_meta is None
    assert plan.recovery is None
    assert plan.completed_years == frozenset()


def test_scan_skips_completed_years_and_targets_next_untouched_year(settings: Settings) -> None:
    write_meta(settings, 1980)
    write_page_file(settings, 1980, 1, ["W1", "W2"])
    write_success(settings, 1980)

    plan = scan(settings)

    assert plan.target is not None
    assert plan.target.year == 1981
    assert plan.completed_years == frozenset({1980})


def test_scan_resumes_in_progress_year(settings: Settings) -> None:
    write_meta(settings, 1980, expected_count=4)
    write_page_file(settings, 1980, 1, ["W1", "W2"])
    write_cursor(settings, 1980, "cursor-2")

    plan = scan(settings)

    assert plan.target is not None
    assert plan.target.year == 1980
    assert plan.target.next_page_number == 2
    assert plan.target.next_cursor == "cursor-2"
    assert plan.target.existing_meta is not None
    assert plan.target.existing_meta.expected_count == 4


def test_scan_reports_missing_cursor_as_recoverable(settings: Settings) -> None:
    # M3: metadata plus pages without _SUCCESS means "in progress", and an
    # in-progress year must have a cursor. The cursor cannot be reconstructed,
    # so scan reports recovery instead of guessing.
    write_meta(settings, 1980)
    write_page_file(settings, 1980, 1, ["W1", "W2"])

    plan = scan(settings)

    assert plan.recovery is not None
    assert plan.recovery.year == 1980
    assert plan.recovery.reason == "missing_cursor"
    assert plan.recovery.action == "discard_year"
    assert plan.target is not None
    assert plan.target.year == 1980
    assert plan.target.next_cursor == "*"


def test_scan_reports_empty_cursor_as_recoverable(settings: Settings) -> None:
    # M3 requires _CURSOR to contain the next cursor, not merely exist.
    # An empty cursor has the same operational recovery as a missing cursor:
    # discard the partial year and restart from cursor="*".
    write_meta(settings, 1980)
    write_page_file(settings, 1980, 1, ["W1", "W2"])
    write_cursor(settings, 1980, "")

    plan = scan(settings)

    assert plan.recovery is not None
    assert plan.recovery.year == 1980
    assert plan.recovery.reason == "empty_cursor"
    assert plan.recovery.action == "discard_year"
    assert plan.target is not None
    assert plan.target.year == 1980
    assert plan.target.next_cursor == "*"


def test_scan_reports_orphan_meta_as_recoverable(settings: Settings) -> None:
    # M2: _META.json is only valid alongside the first page file. A standalone
    # meta file indicates a crash before first-page write completed.
    write_meta(settings, 1980)

    plan = scan(settings)

    assert plan.recovery is not None
    assert plan.recovery.reason == "orphan_meta"
    assert plan.target is not None
    assert plan.target.year == 1980


def test_scan_reports_orphan_pages_as_recoverable(settings: Settings) -> None:
    # M2 in the other direction: page files without _META.json have records but
    # no immutable expected_count target, so the year must restart.
    write_page_file(settings, 1980, 1, ["W1"])

    plan = scan(settings)

    assert plan.recovery is not None
    assert plan.recovery.reason == "orphan_pages"
    assert plan.target is not None
    assert plan.target.year == 1980


def test_scan_raises_on_filter_scope_mismatch(settings: Settings) -> None:
    # M8: a success marker is not enough. Completed years are only reusable if
    # their recorded filter matches the current effective per-year filter.
    write_meta(settings, 1980, filter="primary_topic.field.id:42,publication_year:1980")
    write_page_file(settings, 1980, 1, ["W1", "W2"])
    write_success(settings, 1980)

    with pytest.raises(FilterScopeMismatch):
        scan(settings)


def test_scan_treats_completed_year_with_leftover_cursor_as_complete(
    settings: Settings,
) -> None:
    # _CURSOR is not consulted after _SUCCESS exists. This tolerates harmless
    # leftovers from interrupted finalization while preserving M8 validation.
    write_meta(settings, 1980)
    write_page_file(settings, 1980, 1, ["W1", "W2"])
    write_cursor(settings, 1980, "stale-leftover")
    write_success(settings, 1980)

    plan = scan(settings)

    assert plan.target is not None
    assert plan.target.year == 1981
    assert plan.completed_years == frozenset({1980})


def test_scan_raises_when_completed_year_is_missing_meta(settings: Settings) -> None:
    # _SUCCESS without _META.json cannot pass M8 filter validation and should
    # not be treated as a reusable completed year.
    write_page_file(settings, 1980, 1, ["W1", "W2"])
    write_success(settings, 1980)

    with pytest.raises(CorruptedYearState):
        scan(settings)


def test_scan_raises_on_page_numbering_gap(settings: Settings) -> None:
    # M4: a gap means the on-disk sequence no longer maps cleanly to cursor
    # progression. This is treated as corruption, not automatic recovery.
    write_meta(settings, 1980, expected_count=2)
    write_page_file(settings, 1980, 1, ["W1"])
    write_page_file(settings, 1980, 3, ["W3"])
    write_cursor(settings, 1980, "cursor-4")

    with pytest.raises(CorruptedYearState):
        scan(settings)


def test_scan_returns_all_complete_when_every_year_in_range_has_success(
    settings: Settings,
) -> None:
    for year in [1980, 1981, 1982]:
        write_meta(settings, year)
        write_page_file(settings, year, 1, ["W1", "W2"])
        write_success(settings, year)

    plan = scan(settings)

    assert plan.target is None
    assert plan.recovery is None
    assert plan.completed_years == frozenset({1980, 1981, 1982})


def test_scan_treats_empty_existing_directory_as_untouched(settings: Settings) -> None:
    year_dir(settings, 1980).mkdir(parents=True)

    plan = scan(settings)

    assert plan.target is not None
    assert plan.target.year == 1980
    assert plan.recovery is None
