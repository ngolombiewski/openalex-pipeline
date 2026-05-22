from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from openalex_pipeline.extraction.settings import Settings


def test_settings_constructs_from_kwargs() -> None:
    s = Settings(
        api_key="k",
        filter="primary_topic.field.id:17",
        start_year=1980,
        end_year=1982,
        data_dir=Path("/data"),
    )

    assert s.api_key == "k"
    assert s.filter == "primary_topic.field.id:17"
    assert s.start_year == 1980
    assert s.end_year == 1982
    assert s.data_dir == Path("/data")


def test_settings_years_is_inclusive_range() -> None:
    s = Settings(
        api_key="k",
        filter="filter=x",
        start_year=1980,
        end_year=1982,
        data_dir=Path("/data"),
    )

    assert s.years == [1980, 1981, 1982]


def test_settings_years_single_year_when_start_equals_end() -> None:
    s = Settings(
        api_key="k",
        filter="filter=x",
        start_year=2020,
        end_year=2020,
        data_dir=Path("/data"),
    )

    assert s.years == [2020]


def test_settings_rejects_swapped_year_bounds() -> None:
    with pytest.raises(ValidationError):
        Settings(
            api_key="k",
            filter="filter=x",
            start_year=2020,
            end_year=2019,
            data_dir=Path("/data"),
        )


def test_settings_loads_all_fields_from_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # chdir into tmp_path so the project's real .env file is not picked up.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENALEX_API_KEY", "k")
    monkeypatch.setenv("OPENALEX_FILTER", "primary_topic.field.id:17")
    monkeypatch.setenv("OPENALEX_START_YEAR", "1980")
    monkeypatch.setenv("OPENALEX_END_YEAR", "1982")
    monkeypatch.setenv("OPENALEX_DATA_DIR", str(tmp_path / "extract"))

    s = Settings()  # type: ignore[call-arg]

    assert s.api_key == "k"
    assert s.filter == "primary_topic.field.id:17"
    assert s.start_year == 1980
    assert s.end_year == 1982
    assert s.data_dir == tmp_path / "extract"
    assert s.years == [1980, 1981, 1982]


def test_settings_raises_when_required_env_var_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    for var in (
        "OPENALEX_API_KEY",
        "OPENALEX_FILTER",
        "OPENALEX_START_YEAR",
        "OPENALEX_END_YEAR",
        "OPENALEX_DATA_DIR",
    ):
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]
