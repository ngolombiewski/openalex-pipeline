from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openalex_pipeline.extraction.config import Settings
from openalex_pipeline.extraction.constants import (
    CURSOR_FILENAME,
    META_FILENAME,
    PAGE_FILENAME_TEMPLATE,
    SUCCESS_FILENAME,
    YEAR_DIR_TEMPLATE,
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        api_key="test-key",
        output_dir=tmp_path / "works",
        filter="primary_topic.field.id:17",
        year_range="1980-1982",
        per_page=2,
        max_retries=2,
    )


def year_dir(settings: Settings, year: int) -> Path:
    return settings.output_dir / YEAR_DIR_TEMPLATE.format(year=year)


def write_meta(
    settings: Settings,
    year: int,
    *,
    filter: str | None = None,
    expected_count: int = 2,
    started_at: str = "2026-05-19T10:30:00Z",
) -> Path:
    path = year_dir(settings, year)
    path.mkdir(parents=True, exist_ok=True)
    meta_path = path / META_FILENAME
    meta_path.write_text(
        json.dumps(
            {
                "filter": filter or f"{settings.filter},publication_year:{year}",
                "expected_count": expected_count,
                "started_at": started_at,
            }
        ),
        encoding="utf-8",
    )
    return meta_path


def write_cursor(settings: Settings, year: int, cursor: str = "cursor-next") -> Path:
    path = year_dir(settings, year)
    path.mkdir(parents=True, exist_ok=True)
    cursor_path = path / CURSOR_FILENAME
    cursor_path.write_text(cursor, encoding="utf-8")
    return cursor_path


def write_success(settings: Settings, year: int) -> Path:
    path = year_dir(settings, year)
    path.mkdir(parents=True, exist_ok=True)
    success_path = path / SUCCESS_FILENAME
    success_path.write_text("", encoding="utf-8")
    return success_path


def assert_year_complete(settings: Settings, year: int) -> None:
    assert (year_dir(settings, year) / SUCCESS_FILENAME).exists()


def write_page_file(settings: Settings, year: int, page_number: int, ids: list[str]) -> Path:
    path = year_dir(settings, year)
    path.mkdir(parents=True, exist_ok=True)
    page_path = path / PAGE_FILENAME_TEMPLATE.format(number=page_number)
    page_path.write_text(
        "".join(json.dumps({"id": id_}) + "\n" for id_ in ids),
        encoding="utf-8",
    )
    return page_path


def utc_datetime() -> datetime:
    return datetime(2026, 5, 19, 10, 30, tzinfo=UTC)
