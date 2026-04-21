#!/usr/bin/env python3
"""OpenAlex bulk metadata downloader — writes JSONL batches with resume support."""

import argparse
import signal
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import orjson
import requests
from loguru import logger
from pydantic_settings import BaseSettings

# Bronze layer columns per DATA_MODEL.md
SELECTED_FIELDS: list[str] = [
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
]

OPENALEX_BASE = "https://api.openalex.org"
PER_PAGE = 200
LARGE_DATASET_THRESHOLD = 2_000_000
CHECKPOINT_FILENAME = ".checkpoint.json"
LOG_FILENAME = "download.log"


class Settings(BaseSettings):
    openalex_api_key: str = ""

    class Config:
        env_prefix = "OPENALEX_"


@dataclass
class Checkpoint:
    filter_str: str
    cursor: str
    batch_index: int
    records_written: int
    records_skipped: int


class OpenAlexDownloader:
    def __init__(self, output_dir: Path, filter_str: str, api_key: str) -> None:
        self.output_dir = output_dir
        self.filter_str = filter_str
        self.api_key = api_key
        self._shutdown = False
        self._session = requests.Session()

        output_dir.mkdir(parents=True, exist_ok=True)

        logger.remove()
        logger.add(sys.stderr, level="INFO")
        logger.add(
            output_dir / LOG_FILENAME,
            level="DEBUG",
            rotation="100 MB",
            encoding="utf-8",
        )

        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum: int, frame: object) -> None:
        logger.info("shutdown signal received — will stop after current batch")
        self._shutdown = True

    def run(self) -> None:
        expected = self._preflight()

        checkpoint = self._load_checkpoint()
        if checkpoint is not None:
            if checkpoint.filter_str != self.filter_str:
                logger.error(
                    "checkpoint filter mismatch: saved={!r} current={!r} — refusing to overwrite",
                    checkpoint.filter_str,
                    self.filter_str,
                )
                sys.exit(1)
            logger.info(
                "resuming from batch {} | {} records already written",
                checkpoint.batch_index,
                checkpoint.records_written,
            )
            cursor = checkpoint.cursor
            batch_index = checkpoint.batch_index
            records_written = checkpoint.records_written
            records_skipped = checkpoint.records_skipped
        else:
            logger.info("starting fresh download")
            cursor = "*"
            batch_index = 0
            records_written = 0
            records_skipped = 0

        while cursor and not self._shutdown:
            t0 = time.monotonic()
            records, next_cursor = self._fetch_page(cursor)
            elapsed = time.monotonic() - t0

            valid = [r for r in records if "id" in r]
            skipped = len(records) - len(valid)
            if skipped:
                logger.warning(
                    "batch {} | skipped {} records missing 'id'", batch_index, skipped
                )
            records_skipped += skipped

            if valid:
                self._write_batch(valid, batch_index)

            records_written += len(valid)
            rate = len(valid) / elapsed if elapsed > 0 else 0
            logger.info(
                "batch {} | {} records | {:.0f} rec/s | cursor: {}",
                batch_index,
                len(valid),
                rate,
                next_cursor or "done",
            )

            batch_index += 1
            cursor = next_cursor or ""

            self._save_checkpoint(
                Checkpoint(
                    filter_str=self.filter_str,
                    cursor=cursor,
                    batch_index=batch_index,
                    records_written=records_written,
                    records_skipped=records_skipped,
                )
            )

        if self._shutdown:
            logger.info("shutdown complete | {} records written", records_written)
        else:
            logger.info(
                "download complete | {} records written | {} skipped",
                records_written,
                records_skipped,
            )

    def _preflight(self) -> int:
        logger.info("running pre-flight check for filter: {!r}", self.filter_str)
        params: dict[str, str | int] = {
            "filter": self.filter_str,
            "per-page": 1,
        }
        if self.api_key:
            params["api_key"] = self.api_key

        resp = self._session.get(f"{OPENALEX_BASE}/works", params=params, timeout=30)
        resp.raise_for_status()

        data = orjson.loads(resp.content)
        count: int = data["meta"]["count"]
        logger.info("expected records: {}", count)

        if count > LARGE_DATASET_THRESHOLD:
            logger.warning(
                "large dataset ({} records) — consider adding a publication_year filter to narrow the scope",
                count,
            )

        return count

    def _load_checkpoint(self) -> Checkpoint | None:
        path = self.output_dir / CHECKPOINT_FILENAME
        if not path.exists():
            return None
        data = orjson.loads(path.read_bytes())
        return Checkpoint(**data)

    def _save_checkpoint(self, checkpoint: Checkpoint) -> None:
        path = self.output_dir / CHECKPOINT_FILENAME
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(orjson.dumps(asdict(checkpoint), option=orjson.OPT_INDENT_2))
        tmp.rename(path)

    def _fetch_page(self, cursor: str) -> tuple[list[dict], str | None]:
        params: dict[str, str | int] = {
            "filter": self.filter_str,
            "cursor": cursor,
            "per-page": PER_PAGE,
        }
        if self.api_key:
            params["api_key"] = self.api_key

        url = f"{OPENALEX_BASE}/works"
        backoff_delays = [5, 10, 20]

        for attempt, delay in enumerate(backoff_delays + [None], start=1):  # type: ignore[list-item]
            try:
                resp = self._session.get(url, params=params, timeout=60)
            except requests.RequestException as exc:
                if delay is None:
                    raise
                logger.warning(
                    "request error (attempt {}): {} — retrying in {}s",
                    attempt,
                    exc,
                    delay,
                )
                time.sleep(delay)
                continue

            if resp.status_code == 429:
                remaining = resp.headers.get("X-RateLimit-Remaining")
                required = resp.headers.get("X-RateLimit-Credits-Required")
                if remaining is not None and required is not None:
                    try:
                        if int(remaining) < int(required):
                            raise RuntimeError(
                                f"rate limit credits exhausted "
                                f"(remaining={remaining}, required={required}) — checkpoint saved"
                            )
                    except ValueError:
                        pass

                retry_after = int(resp.headers.get("Retry-After", 60))
                logger.warning("429 rate limited — sleeping {}s", retry_after)
                time.sleep(retry_after)
                continue

            if resp.status_code >= 500:
                if delay is None:
                    resp.raise_for_status()
                logger.warning(
                    "HTTP {} (attempt {}) — retrying in {}s",
                    resp.status_code,
                    attempt,
                    delay,
                )
                time.sleep(delay)
                continue

            resp.raise_for_status()
            data = orjson.loads(resp.content)
            records: list[dict] = data.get("results", [])
            next_cursor: str | None = data.get("meta", {}).get("next_cursor")
            return records, next_cursor

        raise RuntimeError("all retry attempts exhausted")

    def _write_batch(self, records: list[dict], batch_index: int) -> None:
        path = self._batch_path(batch_index)
        tmp = path.with_suffix(".tmp")
        lines = b"\n".join(
            orjson.dumps({k: r[k] for k in SELECTED_FIELDS if k in r}) for r in records
        )
        tmp.write_bytes(lines + b"\n")
        tmp.rename(path)

    def _batch_path(self, batch_index: int) -> Path:
        return self.output_dir / f"batch_{batch_index:06d}.jsonl"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download OpenAlex works to JSONL batches"
    )
    parser.add_argument(
        "--filter", required=True, dest="filter_str", help="OpenAlex filter string"
    )
    parser.add_argument("--output", required=True, type=Path, help="Output directory")
    args = parser.parse_args()

    settings = Settings()
    downloader = OpenAlexDownloader(
        output_dir=args.output,
        filter_str=args.filter_str,
        api_key=settings.openalex_api_key,
    )
    downloader.run()


if __name__ == "__main__":
    main()
