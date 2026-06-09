"""Upload CLI entrypoint: `python -m openalex_pipeline.upload`.

Intentionally thin: parse args, resolve the bronze root and bucket, build the
GCS client, call run(). Per-year progress logging lives in the runner. No
upload or skip logic lives here.

A plain module for now, mirroring extraction and bronze; it will become a
Dagster asset later.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from google.cloud import storage

from .runner import run

OPENALEX_DATA_ROOT_ENV = "OPENALEX_DATA_ROOT"
"""Env var naming the project data root. Upload reads {root}/bronze. A DEFAULT
only -- the --bronze-root flag overrides it."""

OPENALEX_GCS_BUCKET_ENV = "OPENALEX_GCS_BUCKET"
"""Env var naming the destination GCS bucket. The --bucket flag overrides it.
No default: the bucket is project-specific and must be supplied explicitly."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="upload",
        description="Upload bronze Parquet files to GCS, Hive-partitioned for BigQuery.",
    )
    parser.add_argument(
        "--bronze-root", type=Path, default=None,
        help="Bronze input directory. Default: {OPENALEX_DATA_ROOT}/bronze.",
    )
    parser.add_argument(
        "--bucket", type=str, default=None,
        help=f"Destination GCS bucket. Default: ${OPENALEX_GCS_BUCKET_ENV}.",
    )
    return parser.parse_args(argv)


def resolve_bronze_root(args: argparse.Namespace) -> Path:
    """Resolve the bronze root: the --bronze-root flag, else {DATA_ROOT}/bronze.

    Raises:
        SystemExit: neither the flag nor OPENALEX_DATA_ROOT is set, or the
            resolved directory does not exist.
    """
    if args.bronze_root is not None:
        bronze_root = args.bronze_root
    else:
        data_root = os.environ.get(OPENALEX_DATA_ROOT_ENV)
        if data_root is None:
            raise SystemExit(
                f"--bronze-root not given and {OPENALEX_DATA_ROOT_ENV} is not set"
            )
        bronze_root = Path(data_root) / "bronze"

    if not bronze_root.exists():
        raise SystemExit(f"bronze root does not exist: {bronze_root}")
    return bronze_root


def resolve_bucket_name(args: argparse.Namespace) -> str:
    """Resolve the bucket name: the --bucket flag, else the env var.

    Raises:
        SystemExit: neither the flag nor OPENALEX_GCS_BUCKET is set.
    """
    if args.bucket is not None:
        return args.bucket
    bucket = os.environ.get(OPENALEX_GCS_BUCKET_ENV)
    if bucket is None:
        raise SystemExit(
            f"--bucket not given and {OPENALEX_GCS_BUCKET_ENV} is not set"
        )
    return bucket


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint. Authenticates via ADC (no key file)."""
    args = parse_args(argv)
    bronze_root = resolve_bronze_root(args)
    bucket_name = resolve_bucket_name(args)

    client = storage.Client()
    bucket = client.bucket(bucket_name)

    run(bronze_root, bucket)


if __name__ == "__main__":
    main()
