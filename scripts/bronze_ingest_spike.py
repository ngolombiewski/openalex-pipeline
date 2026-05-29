"""Read-only Polars spike for the bronze ingestion design.

This script answers implementation questions before the real ingestion module
exists. It samples completed extraction years, compares inferred NDJSON schemas,
and checks whether nested fields can be encoded to JSON strings.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

import polars as pl


BRONZE_COLUMNS = [
    "id",
    "title",
    "publication_year",
    "publication_date",
    "type",
    "language",
    "is_retracted",
    "is_paratext",
    "primary_topic",
    "topics",
    "cited_by_count",
    "counts_by_year",
    "cited_by_percentile_year",
    "citation_normalized_percentile",
    "fwci",
    "referenced_works_count",
    "open_access",
    "doi",
    "ids",
    "keywords",
    "updated_date",
]

NESTED_COLUMNS = [
    "primary_topic",
    "topics",
    "counts_by_year",
    "cited_by_percentile_year",
    "citation_normalized_percentile",
    "open_access",
    "ids",
    "keywords",
]


def _default_extract_dir() -> Path:
    return Path("data/dev/extract")


def _bronze_schema(nested_dtype: pl.DataType = pl.String) -> dict[str, pl.DataType]:
    return {
        "id": pl.String,
        "title": pl.String,
        "publication_year": pl.Int64,
        "publication_date": pl.String,
        "type": pl.String,
        "language": pl.String,
        "is_retracted": pl.Boolean,
        "is_paratext": pl.Boolean,
        "primary_topic": nested_dtype,
        "topics": nested_dtype,
        "cited_by_count": pl.Int64,
        "counts_by_year": nested_dtype,
        "cited_by_percentile_year": nested_dtype,
        "citation_normalized_percentile": nested_dtype,
        "fwci": pl.Float64,
        "referenced_works_count": pl.Int64,
        "open_access": nested_dtype,
        "doi": pl.String,
        "ids": nested_dtype,
        "keywords": nested_dtype,
        "updated_date": pl.String,
    }


def _completed_years(extract_dir: Path) -> list[int]:
    years: list[int] = []
    for child in extract_dir.iterdir():
        if child.is_dir() and child.name.isdigit() and (child / "_YEAR_REPORT.json").exists():
            years.append(int(child.name))
    return sorted(years)


def _page_files(extract_dir: Path, year: int) -> list[Path]:
    return sorted((extract_dir / str(year)).glob("page-*.jsonl"))


def _schema_signature(schema: dict[str, pl.DataType]) -> tuple[tuple[str, str], ...]:
    return tuple((name, str(dtype)) for name, dtype in schema.items())


def _load_report(extract_dir: Path, year: int) -> dict[str, Any]:
    report_path = extract_dir / str(year) / "_YEAR_REPORT.json"
    return json.loads(report_path.read_text(encoding="utf-8"))


def _raw_records(path: Path, limit: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as file:
        for line in file:
            if len(records) >= limit:
                break
            records.append(json.loads(line))
    return records


def _print_schema(schema: dict[str, pl.DataType]) -> None:
    for name, dtype in schema.items():
        print(f"    {name}: {dtype}")


def _non_null_value(frame: pl.DataFrame, column: str) -> Any | None:
    values = frame[column].drop_nulls().head(1).to_list()
    return values[0] if values else None


def _first_non_null_row(records: list[dict[str, Any]], column: str) -> int | None:
    for index, record in enumerate(records):
        if record.get(column) is not None:
            return index
    return None


def inspect_schema_uniformity(extract_dir: Path, years: list[int]) -> None:
    print("\n== Schema Uniformity ==")
    signatures: dict[tuple[tuple[str, str], ...], list[int]] = {}

    for year in years:
        page_files = _page_files(extract_dir, year)
        if not page_files:
            print(f"{year}: no page files")
            continue

        schema = pl.scan_ndjson(page_files[0]).collect_schema()
        signature = _schema_signature(dict(schema))
        signatures.setdefault(signature, []).append(year)
        print(f"{year}: {page_files[0].name}")
        _print_schema(dict(schema))

    print(f"\nDistinct first-page schemas: {len(signatures)}")
    for index, (_, signature_years) in enumerate(signatures.items(), start=1):
        display_years = ", ".join(str(year) for year in signature_years)
        print(f"  schema {index}: {display_years}")


def inspect_forced_string_schema(extract_dir: Path, years: list[int]) -> None:
    print("\n== Forced Schema Over Full Shards ==")
    mixed_schema = _bronze_schema(nested_dtype=pl.String)
    frames: list[pl.DataFrame] = []

    for year in years:
        page_files = _page_files(extract_dir, year)
        if not page_files:
            print(f"{year}: no page files")
            continue

        report = _load_report(extract_dir, year)
        try:
            frame = pl.scan_ndjson(page_files, schema=mixed_schema).select(BRONZE_COLUMNS).collect()
        except Exception as exc:  # noqa: BLE001 - spike reports parser behavior.
            print(f"{year}: forced bronze mixed schema failed: {type(exc).__name__}: {exc}")
            continue

        frames.append(frame)
        print(
            f"{year}: forced bronze mixed schema collected "
            f"rows={frame.height} expected={report['records_fetched']}"
        )
        print(f"{year}: schema={frame.schema}")

    if len(frames) < 2:
        print("concat: skipped; need at least two collected years")
        return

    try:
        concatenated = pl.concat(frames, how="vertical")
    except Exception as exc:  # noqa: BLE001 - spike reports concat behavior.
        print(f"concat: failed: {type(exc).__name__}: {exc}")
        return

    print(f"concat: succeeded rows={concatenated.height} years={years}")


def inspect_forced_string_json_round_trip(extract_dir: Path, year: int) -> None:
    print("\n== Forced String JSON Round Trip ==")
    page_files = _page_files(extract_dir, year)
    if not page_files:
        print(f"{year}: no page files")
        return

    mixed_schema = _bronze_schema(nested_dtype=pl.String)
    try:
        forced = pl.scan_ndjson(page_files[0], schema=mixed_schema).select(BRONZE_COLUMNS).head(20).collect()
    except Exception as exc:  # noqa: BLE001 - spike reports the actual parser behavior.
        print(f"{year}: forced mixed schema failed before round trip: {type(exc).__name__}: {exc}")
        return

    try:
        inferred = pl.scan_ndjson(page_files[0]).select(BRONZE_COLUMNS).head(20).collect()
    except Exception as exc:  # noqa: BLE001 - spike reports the actual parser behavior.
        print(f"{year}: inferred schema failed before round trip: {type(exc).__name__}: {exc}")
        return

    raw_records = _raw_records(page_files[0], limit=20)

    for column in NESTED_COLUMNS:
        row_index = _first_non_null_row(raw_records, column)
        if row_index is None:
            print(f"  {column}: no non-null raw value in sample")
            continue

        forced_value = forced[column][row_index]
        if forced_value is None:
            print(f"  {column}: forced value is null where raw value is present")
            continue

        try:
            forced_decoded = json.loads(forced_value)
        except json.JSONDecodeError as exc:
            print(f"  {column}: forced String is not valid JSON: {exc}; sample={forced_value!r}")
            continue

        try:
            encoded = inferred.select(pl.col(column).struct.json_encode().alias(column))
            encoded_value = _non_null_value(encoded, column)
            encoded_decoded = json.loads(encoded_value) if encoded_value is not None else None
        except Exception as exc:  # noqa: BLE001 - spike reports encoder behavior.
            print(f"  {column}: baseline json_encode failed: {type(exc).__name__}: {exc}")
            continue

        matches_raw = forced_decoded == raw_records[row_index][column]
        matches_encoded = forced_decoded == encoded_decoded
        print(
            f"  {column}: forced String parses as JSON; "
            f"matches raw={matches_raw}; matches json_encode={matches_encoded}; "
            f"sample={forced_value[:160]!r}"
        )


def inspect_json_encoding(extract_dir: Path, year: int) -> None:
    print("\n== Nested JSON Encoding ==")
    page_files = _page_files(extract_dir, year)
    if not page_files:
        print(f"{year}: no page files")
        return

    frame = pl.scan_ndjson(page_files[0]).select(BRONZE_COLUMNS).head(3).collect()
    print(f"{year}: sampled rows={frame.height}")

    for column in NESTED_COLUMNS:
        if column not in frame.columns:
            print(f"  {column}: missing")
            continue

        dtype = frame.schema[column]
        try:
            encoded = frame.select(pl.col(column).struct.json_encode().alias(column))
            value = encoded[column].drop_nulls().head(1).to_list()
            print(f"  {column}: struct.json_encode ok ({dtype}); sample={value[:1]}")
        except Exception as struct_exc:  # noqa: BLE001 - spike reports API fit.
            try:
                encoded = frame.select(
                    pl.col(column)
                    .map_elements(
                        lambda value: json.dumps(value) if value is not None else None,
                        return_dtype=pl.String,
                    )
                    .alias(column)
                )
                value = encoded[column].drop_nulls().head(1).to_list()
                print(
                    f"  {column}: map_elements json.dumps ok ({dtype}); "
                    f"struct path failed with {type(struct_exc).__name__}; sample={value[:1]}"
                )
            except Exception as map_exc:  # noqa: BLE001 - spike reports API fit.
                print(
                    f"  {column}: encode failed ({dtype}); "
                    f"struct={type(struct_exc).__name__}: {struct_exc}; "
                    f"map={type(map_exc).__name__}: {map_exc}"
                )


def inspect_zero_byte_behavior() -> None:
    print("\n== Zero-Byte NDJSON Behavior ==")
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "empty.jsonl"
        path.write_bytes(b"")
        try:
            frame = pl.scan_ndjson(path).collect()
        except Exception as exc:  # noqa: BLE001 - spike reports the actual parser behavior.
            print(f"zero-byte file failed: {type(exc).__name__}: {exc}")
            return

        print(f"zero-byte file succeeded: rows={frame.height}, columns={frame.columns}")


def inspect_count_and_duplicate_checks(extract_dir: Path, year: int) -> None:
    print("\n== Count And ID Checks On One Year ==")
    page_files = _page_files(extract_dir, year)
    if not page_files:
        print(f"{year}: no page files")
        return

    report = _load_report(extract_dir, year)
    frame = pl.scan_ndjson(page_files).select("id").collect()
    row_count = frame.height
    null_id_count = frame.select(pl.col("id").is_null().sum()).item()
    duplicate_id_count = row_count - frame.select(pl.col("id").n_unique()).item()

    print(f"{year}: extraction records_fetched={report['records_fetched']}")
    print(f"{year}: polars row_count={row_count}")
    print(f"{year}: null_id_count={null_id_count}")
    print(f"{year}: duplicate_id_count={duplicate_id_count}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--extract-dir",
        type=Path,
        default=_default_extract_dir(),
        help="Extraction directory to inspect. Defaults to data/dev/extract.",
    )
    parser.add_argument(
        "--years",
        nargs="*",
        type=int,
        help="Specific completed years to inspect. Defaults to up to five completed years.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    extract_dir = args.extract_dir
    if not extract_dir.exists():
        raise SystemExit(f"extract dir does not exist: {extract_dir}")

    available_years = _completed_years(extract_dir)
    if args.years:
        years = [year for year in args.years if year in available_years]
        missing = sorted(set(args.years) - set(years))
        if missing:
            print(f"Skipping non-completed/missing years: {missing}")
    else:
        years = available_years[:5]

    if not years:
        raise SystemExit(f"no completed years found in {extract_dir}")

    print(f"extract_dir={extract_dir}")
    print(f"years={years}")

    inspect_schema_uniformity(extract_dir, years)
    inspect_forced_string_schema(extract_dir, years)
    inspect_forced_string_json_round_trip(extract_dir, years[0])
    inspect_json_encoding(extract_dir, years[0])
    inspect_zero_byte_behavior()
    inspect_count_and_duplicate_checks(extract_dir, years[-1])


if __name__ == "__main__":
    main()
