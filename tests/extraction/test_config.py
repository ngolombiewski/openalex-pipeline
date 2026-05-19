from __future__ import annotations

import pytest
from freezegun import freeze_time

from openalex_pipeline.extraction.config import Settings
from openalex_pipeline.extraction.constants import YEAR_FLOOR


@freeze_time("2026-05-19")
def test_resolved_year_range_defaults_to_floor_through_current_year() -> None:
    settings = Settings(api_key="test-key")

    assert settings.resolved_year_range() == range(YEAR_FLOOR, 2027)


def test_resolved_year_range_accepts_single_year() -> None:
    settings = Settings(api_key="test-key", year_range="2024")

    assert settings.resolved_year_range() == range(2024, 2025)


def test_resolved_year_range_accepts_inclusive_span() -> None:
    settings = Settings(api_key="test-key", year_range="1980-1982")

    assert settings.resolved_year_range() == range(1980, 1983)


@pytest.mark.parametrize(
    "year_range",
    [
        "bad",
        "1980-",
        "1982-1980",
        f"{YEAR_FLOOR - 1}",
        "3026",
    ],
)
def test_resolved_year_range_rejects_malformed_or_out_of_scope_values(
    year_range: str,
) -> None:
    settings = Settings(api_key="test-key", year_range=year_range)

    with pytest.raises(ValueError):
        settings.resolved_year_range()
