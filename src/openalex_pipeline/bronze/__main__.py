"""Bronze CLI entrypoint: `python -m openalex_pipeline.bronze`.

Intentionally thin: parse args, build the years list, call run(), log a summary.
No classification or ingestion logic lives here.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from loguru import logger

from .runner import run

OPENALEX_DATA_ROOT_ENV = "OPENALEX_DATA_ROOT"
"""Env var naming the project data root. extraction uses {root}/extract; bronze
uses {root}/bronze and reads {root}/extract. A DEFAULT only -- the
--extract-root / --bronze-root flags override it."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="bronze",
        description="Convert completed extraction years to bronze Parquet.",
    )
    parser.add_argument(
        "--extract-root", type=Path, default=None,
        help="Extraction input directory. Default: {OPENALEX_DATA_ROOT}/extract.",
    )
    parser.add_argument(
        "--bronze-root", type=Path, default=None,
        help="Bronze output directory. Default: {OPENALEX_DATA_ROOT}/bronze.",
    )
    parser.add_argument(
        "--years", type=str, default=None,
        help="Inclusive year range START:END. If omitted, discover completed years.",
    )
    return parser.parse_args(argv)


def resolve_roots(args: argparse.Namespace) -> tuple[Path, Path]:
    """Resolve (extract_root, bronze_root) from CLI args and the environment.

    Precedence per root: the explicit flag, else {OPENALEX_DATA_ROOT}/<name>.

    Raises:
        SystemExit: neither the flag nor OPENALEX_DATA_ROOT is set, or
            extract_root does not exist.
    """
    data_root = os.environ.get(OPENALEX_DATA_ROOT_ENV)
    base = Path(data_root) if data_root else None

    extract_root = _resolve_one(args.extract_root, base, "extract", "--extract-root")
    bronze_root = _resolve_one(args.bronze_root, base, "bronze", "--bronze-root")

    if not extract_root.exists():
        raise SystemExit(f"extract root does not exist: {extract_root}")

    return extract_root, bronze_root


def build_years_list(extract_root: Path, years_arg: str | None) -> list[int]:
    """Construct the list of years to process.

    Explicit range ("START:END"): the inclusive integer range -- the universe.
    Default (None): every numeric subdirectory of extract_root, sorted.

    Raises:
        SystemExit: years_arg is malformed, START > END, or the default scan
            finds no numeric subdirectories.
    """
    if years_arg is None:
        years = sorted(
            int(child.name)
            for child in extract_root.iterdir()
            if child.is_dir() and child.name.isdigit()
        )
        if not years:
            raise SystemExit(f"no numeric year subdirectories found in {extract_root}")
        return years

    parts = years_arg.split(":")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise SystemExit(f"malformed --years range: {years_arg!r} (expected START:END)")
    try:
        start, end = int(parts[0]), int(parts[1])
    except ValueError:
        raise SystemExit(f"malformed --years range: {years_arg!r} (expected integers)")
    if start > end:
        raise SystemExit(f"--years range start {start} > end {end}")
    return list(range(start, end + 1))


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint. BronzeError subclasses propagate as loud failures."""
    args = parse_args(argv)
    extract_root, bronze_root = resolve_roots(args)
    years = build_years_list(extract_root, args.years)
    manifest = run(extract_root, bronze_root, years)
    _log_summary(manifest)


# --- Internal ---------------------------------------------------------------

def _resolve_one(flag: Path | None, base: Path | None, name: str, flag_name: str) -> Path:
    if flag is not None:
        return flag
    if base is not None:
        return base / name
    raise SystemExit(
        f"{flag_name} not given and {OPENALEX_DATA_ROOT_ENV} is not set"
    )


def _log_summary(manifest) -> None:
    """Log a per-year summary, surfacing non-blocking warnings (smoke alarms)."""
    for row in manifest.iter_rows(named=True):
        year = row["publication_year"]
        logger.info(
            f"{year}: {row['status']} "
            f"(bronze_row_count={row['bronze_row_count']})"
        )
        if row["duplicate_id_count"]:
            logger.warning(
                f"{year}: {row['duplicate_id_count']} duplicate id(s) in bronze "
                "(non-blocking; cause may be source churn or disk corruption)"
            )
        if row["count_mismatch"]:
            logger.warning(
                f"{year}: extraction reported count_mismatch (non-blocking)"
            )


if __name__ == "__main__":
    main()
