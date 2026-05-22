from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "works"


@pytest.fixture
def query() -> str:
    return "works?filter=primary_topic.field.id:17,publication_year:1980&per_page=200"


def year_dir(root: Path, year: int) -> Path:
    return root / str(year)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_meta(
    root: Path,
    year: int,
    *,
    query: str,
    expected_count: int = 2,
    started_at: str = "2026-05-19T10:30:00Z",
) -> Path:
    path = year_dir(root, year)
    path.mkdir(parents=True, exist_ok=True)
    meta_path = path / "_META.json"
    meta_path.write_text(
        json.dumps(
            {
                "query": query,
                "expected_count": expected_count,
                "started_at": started_at,
            }
        ),
        encoding="utf-8",
    )
    return meta_path


def write_cursor(
    root: Path,
    year: int,
    *,
    cursor: str | None = "cursor-next",
    next_page: int = 2,
) -> Path:
    path = year_dir(root, year)
    path.mkdir(parents=True, exist_ok=True)
    cursor_path = path / "_CURSOR.json"
    cursor_path.write_text(
        json.dumps({"cursor": cursor, "next_page": next_page}),
        encoding="utf-8",
    )
    return cursor_path


def write_page_file(
    root: Path,
    year: int,
    page_number: int,
    records: list[dict[str, Any]],
) -> Path:
    path = year_dir(root, year)
    path.mkdir(parents=True, exist_ok=True)
    page_path = path / f"page-{page_number:04d}.jsonl"
    page_path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    return page_path


def write_year_report(
    root: Path,
    year: int,
    *,
    query: str,
    started_at: str = "2026-05-19T10:30:00Z",
    completed_at: str = "2026-05-19T10:45:00Z",
    expected_count: int = 2,
    records_fetched: int = 2,
    page_count: int = 1,
    count_mismatch: bool = False,
) -> Path:
    path = year_dir(root, year)
    path.mkdir(parents=True, exist_ok=True)
    report_path = path / "_YEAR_REPORT.json"
    report_path.write_text(
        json.dumps(
            {
                "query": query,
                "year": year,
                "started_at": started_at,
                "completed_at": completed_at,
                "expected_count": expected_count,
                "records_fetched": records_fetched,
                "page_count": page_count,
                "count_mismatch": count_mismatch,
            }
        ),
        encoding="utf-8",
    )
    return report_path
