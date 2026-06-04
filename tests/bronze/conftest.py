"""Fixtures and builders for the bronze ingestion tests.

The natural fixture for bronze is a tmp directory laid out like real extraction
output: numeric year subdirectories, each holding ``_YEAR_REPORT.json`` and one
or more ``page-*.jsonl`` files. Everything here builds that layout (or a
deliberately corrupt variant of it) on a real filesystem; the tests then run
real Polars over it. Nothing is mocked.

See ``docs/bronze-tests.md`` for the test plan these support.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest

# Sentinel: pass ``make_record(field=_OMIT)`` to drop a key entirely (vs. setting
# it to None). Needed to build a record that omits a nested key, which is how the
# forced-String "no fabricated keys" property is exercised.
_OMIT = object()


# --- Path fixtures ----------------------------------------------------------

@pytest.fixture
def extract_root(tmp_path: Path) -> Path:
    """Extraction input directory, created empty."""
    path = tmp_path / "extract"
    path.mkdir()
    return path


@pytest.fixture
def bronze_root(tmp_path: Path) -> Path:
    """Bronze output directory, created empty."""
    path = tmp_path / "bronze"
    path.mkdir()
    return path


# --- Record builder ---------------------------------------------------------

def make_record(id_: str | None = "W1", **overrides: Any) -> dict[str, Any]:
    """One OpenAlex-shaped record with all 21 schema keys, type-correct.

    The eight nested fields are real dict/list objects (not pre-serialized
    strings), so when written to JSONL they become nested JSON and bronze's
    forced-String read lands them as raw JSON text.

    ``overrides`` replaces any field. Use a wrong-typed value to exercise the
    scalar type-conformance invariant (e.g. ``cited_by_count="lots"``), ``id_=
    None`` for the null-id integrity case, or ``field=_OMIT`` to drop a key.
    """
    record: dict[str, Any] = {
        "id": id_,
        "title": "A Study of Things",
        "publication_year": 2002,
        "publication_date": "2002-03-01",
        "type": "article",
        "language": "en",
        "is_retracted": False,
        "is_paratext": False,
        "primary_topic": {"id": "T100", "display_name": "Graph Theory", "score": 0.91},
        "topics": [{"id": "T100", "display_name": "Graph Theory", "score": 0.91}],
        "cited_by_count": 7,
        "counts_by_year": [{"year": 2003, "cited_by_count": 4}, {"year": 2004, "cited_by_count": 3}],
        "cited_by_percentile_year": {"min": 80, "max": 90},
        "citation_normalized_percentile": {"value": 0.73, "is_in_top_1_percent": False},
        "fwci": 1.25,
        "referenced_works_count": 12,
        "open_access": {"is_oa": True, "oa_status": "gold", "any_repository_has_fulltext": False},
        "doi": "https://doi.org/10.1234/example",
        "ids": {"openalex": f"https://openalex.org/{id_}", "doi": "https://doi.org/10.1234/example"},
        "keywords": [{"keyword": "graphs", "score": 0.5}],
        "updated_date": "2024-06-01",
    }
    for key, value in overrides.items():
        if value is _OMIT:
            record.pop(key, None)
        else:
            record[key] = value
    return record


# --- Extraction-year builder ------------------------------------------------

_DEFAULT_QUERY = (
    "works?filter=primary_topic.field.id:17,publication_year:{year}"
    "&select=id,title,publication_year&per_page=200"
)


def make_extract_year(
    extract_root: Path,
    year: int,
    *,
    records: list[dict[str, Any]] | None = None,
    complete: bool = True,
    pages: list[list[dict[str, Any]]] | None = None,
    empty: bool = False,
    report: dict[str, Any] | None = None,
    no_pages: bool = False,
    zero_byte_extra: bool = False,
    extra_zero_byte_pages: int = 0,
) -> Path:
    """Lay out one extraction year directory under ``extract_root``.

    Args:
        records: records for the single ``page-0001.jsonl`` (default: two).
        complete: write ``_YEAR_REPORT.json`` (-> READY); else omit (-> PENDING).
        pages: split records across multiple page files, one per sublist.
        empty: write a single zero-byte ``page-0001.jsonl`` (zero-result year).
        report: overrides merged into the generated ``_YEAR_REPORT.json``.
        no_pages: write the report but zero page files (corruption case C5).
        zero_byte_extra: write a normal ``page-0001.jsonl`` AND an empty
            ``page-0002.jsonl`` (disallowed zero-byte combo, C19).
        extra_zero_byte_pages: write this many additional zero-byte pages on top
            of ``empty`` (so ``empty=True, extra_zero_byte_pages=1`` => two
            zero-byte pages, also a disallowed combo, C19).

    Returns the year directory path.
    """
    year_dir = extract_root / str(year)
    year_dir.mkdir(parents=True, exist_ok=True)

    if empty:
        (year_dir / "page-0001.jsonl").write_bytes(b"")
        for extra in range(extra_zero_byte_pages):
            (year_dir / f"page-{extra + 2:04d}.jsonl").write_bytes(b"")
        total = 0
        page_count = 1 + extra_zero_byte_pages
    elif no_pages:
        total = 0 if records is None else len(records)
        page_count = 0
    elif pages is not None:
        for index, page_records in enumerate(pages, start=1):
            _write_page(year_dir, index, page_records)
        total = sum(len(page_records) for page_records in pages)
        page_count = len(pages)
    else:
        if records is None:
            records = [make_record("W1"), make_record("W2")]
        _write_page(year_dir, 1, records)
        page_count = 1
        total = len(records)
        if zero_byte_extra:
            (year_dir / "page-0002.jsonl").write_bytes(b"")
            page_count = 2

    if complete:
        _write_report(year_dir, year, total=total, page_count=page_count, overrides=report)

    return year_dir


def _write_page(year_dir: Path, page_number: int, records: list[dict[str, Any]]) -> Path:
    path = year_dir / f"page-{page_number:04d}.jsonl"
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def _write_report(
    year_dir: Path,
    year: int,
    *,
    total: int,
    page_count: int,
    overrides: dict[str, Any] | None,
) -> Path:
    report = {
        "query": _DEFAULT_QUERY.format(year=year),
        "year": year,
        "started_at": "2026-05-22T22:52:23Z",
        "completed_at": "2026-05-22T22:52:46Z",
        "expected_count": total,
        "records_fetched": total,
        "page_count": page_count,
        "count_mismatch": False,
    }
    if overrides:
        report.update(overrides)
    path = year_dir / "_YEAR_REPORT.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def corrupt_page_line(page_path: Path, line_no: int = 0, text: str = "{not valid json") -> None:
    """Overwrite one line of an existing page file with broken JSON."""
    lines = page_path.read_text(encoding="utf-8").splitlines()
    lines[line_no] = text
    page_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- Read helpers -----------------------------------------------------------

def read_year_parquet(bronze_root: Path, year: int) -> pl.DataFrame:
    return pl.read_parquet(bronze_root / f"{year}.parquet")


def read_manifest(bronze_root: Path) -> pl.DataFrame:
    return pl.read_parquet(bronze_root / "_MANIFEST.parquet")


def manifest_row(manifest: pl.DataFrame, year: int) -> dict[str, Any]:
    rows = manifest.filter(pl.col("publication_year") == year).to_dicts()
    assert len(rows) == 1, f"expected exactly one manifest row for {year}, got {len(rows)}"
    return rows[0]


def tmp_files(directory: Path) -> list[Path]:
    """Any leftover ``*.tmp`` files — atomic-write tests assert this is empty."""
    return list(directory.glob("*.tmp"))


# --- loguru capture ---------------------------------------------------------

@pytest.fixture
def loguru_messages():
    """Capture loguru output as a list of formatted strings.

    ``main`` emits its summary and warnings through loguru, which pytest's
    ``caplog`` does not see; this adds a sink and tears it down.
    """
    from loguru import logger

    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(str(message)), level="DEBUG")
    try:
        yield messages
    finally:
        logger.remove(sink_id)
