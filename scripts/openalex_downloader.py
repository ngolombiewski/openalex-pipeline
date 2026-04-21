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
from pydantic_settings import BaseSettings, SettingsConfigDict

# Bronze layer columns per DATA_MODEL.md. Applied server-side via OpenAlex `select=`.
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

# Retry budget for transient failures (5xx, network errors). 429s are handled
# separately via an outer loop and do NOT consume this budget.
TRANSIENT_BACKOFF_DELAYS_S = [5, 10, 20]
DEFAULT_RETRY_AFTER_S = 60


class CreditsExhaustedError(Exception):
    """Raised when OpenAlex reports insufficient remaining credits.

    Not a failure — the caller should log and exit cleanly. Checkpoint is
    preserved so the next run resumes where this one left off.
    """


class Settings(BaseSettings):
    openalex_api_key: str


@dataclass
class Checkpoint:
    filter_str: str
    cursor: str
    batch_index: int
    records_written: int
    records_skipped: int
    expected_total: int


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
                raise ValueError(
                    f"checkpoint filter mismatch: "
                    f"saved={checkpoint.filter_str!r} current={self.filter_str!r} — "
                    f"refusing to overwrite a different dataset"
                )
            logger.info(
                "resuming from batch {} | {}/{} records already written",
                checkpoint.batch_index,
                checkpoint.records_written,
                checkpoint.expected_total,
            )
            cursor = checkpoint.cursor
            batch_index = checkpoint.batch_index
            records_written = checkpoint.records_written
            records_skipped = checkpoint.records_skipped
        else:
            logger.info("starting fresh download | expected {} records", expected)
            cursor = "*"
            batch_index = 0
            records_written = 0
            records_skipped = 0

        try:
            while cursor and not self._shutdown:
                t0 = time.monotonic()
                records, next_cursor = self._fetch_page(cursor)
                elapsed = time.monotonic() - t0

                valid = [r for r in records if "id" in r]
                skipped = len(records) - len(valid)
                if skipped:
                    logger.warning(
                        "batch {} | skipped {} records missing 'id'",
                        batch_index,
                        skipped,
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
                        expected_total=expected,
                    )
                )
        except CreditsExhaustedError as exc:
            logger.warning("{} — checkpoint saved, exiting cleanly", exc)
            return

        # Completion summary. `expected` is a snapshot from preflight; for long
        # runs it may drift as OpenAlex indexes new works, so treat a small
        # delta as informational rather than an error.
        total = records_written + records_skipped
        delta = expected - total
        if self._shutdown:
            logger.info(
                "shutdown complete | {}/{} records written ({} skipped)",
                records_written,
                expected,
                records_skipped,
            )
        else:
            logger.info(
                "download complete | {} written | {} skipped | "
                "expected {} | delta {:+d}",
                records_written,
                records_skipped,
                expected,
                delta,
            )
            if abs(delta) > max(100, expected // 1000):
                logger.warning(
                    "large delta between expected ({}) and actual ({}) record "
                    "counts — investigate",
                    expected,
                    total,
                )

    def _preflight(self) -> int:
        logger.info("running pre-flight check for filter: {!r}", self.filter_str)
        params: dict[str, str | int] = {
            "filter": self.filter_str,
            "per-page": 1,
            "api_key": self.api_key,
        }

        resp = self._session.get(f"{OPENALEX_BASE}/works", params=params, timeout=30)
        resp.raise_for_status()

        data = orjson.loads(resp.content)
        count: int = data["meta"]["count"]
        logger.info("expected records: {}", count)

        if count > LARGE_DATASET_THRESHOLD:
            logger.warning(
                "large dataset ({} records) — consider adding a publication_year "
                "filter to narrow the scope",
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
        """Fetch one page. Blocks indefinitely on 429s; bounded retries on 5xx.

        429 (rate limit) and credit-exhaustion are distinct concerns from
        transient failures, so they do NOT consume the retry budget. The outer
        loop handles 429s; the inner loop handles network errors and 5xx.
        """
        params: dict[str, str | int] = {
            "filter": self.filter_str,
            "cursor": cursor,
            "per-page": PER_PAGE,
            "select": ",".join(SELECTED_FIELDS),
            "api_key": self.api_key,
        }
        url = f"{OPENALEX_BASE}/works"

        while True:  # outer loop: retry indefinitely on 429
            resp = self._request_with_transient_retry(url, params)

            # Pre-emptive credit check on every response, not just 429s.
            # If the server tells us the next request would exceed our budget,
            # stop now before making it.
            self._check_credits(resp)

            if resp.status_code == 429:
                retry_after = self._parse_retry_after(resp)
                logger.warning("429 rate limited — sleeping {}s", retry_after)
                time.sleep(retry_after)
                continue

            resp.raise_for_status()
            data = orjson.loads(resp.content)
            records: list[dict] = data.get("results", [])
            next_cursor: str | None = data.get("meta", {}).get("next_cursor")
            return records, next_cursor

    def _request_with_transient_retry(
        self, url: str, params: dict
    ) -> requests.Response:
        """GET with bounded exponential backoff for 5xx and network errors.

        Returns the response for the caller to inspect. 429s are returned
        as-is (the outer loop handles them) and do NOT consume retry budget.
        """
        last_exc: Exception | None = None
        for attempt, delay in enumerate(TRANSIENT_BACKOFF_DELAYS_S, start=1):
            try:
                resp = self._session.get(url, params=params, timeout=60)
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning(
                    "request error (attempt {}/{}): {} — retrying in {}s",
                    attempt,
                    len(TRANSIENT_BACKOFF_DELAYS_S),
                    exc,
                    delay,
                )
                time.sleep(delay)
                continue

            if resp.status_code >= 500:
                logger.warning(
                    "HTTP {} (attempt {}/{}) — retrying in {}s",
                    resp.status_code,
                    attempt,
                    len(TRANSIENT_BACKOFF_DELAYS_S),
                    delay,
                )
                time.sleep(delay)
                continue

            # Includes 2xx, 4xx (incl. 429) — caller decides.
            return resp

        # Final attempt, no more retries — one last try, let exceptions propagate.
        try:
            return self._session.get(url, params=params, timeout=60)
        except requests.RequestException as exc:
            raise RuntimeError(
                f"transient retries exhausted after {len(TRANSIENT_BACKOFF_DELAYS_S)} "
                f"attempts; last error: {last_exc or exc}"
            ) from exc

    @staticmethod
    def _check_credits(resp: requests.Response) -> None:
        """Raise CreditsExhaustedError if the next request would exceed budget."""
        remaining = resp.headers.get("X-RateLimit-Remaining")
        required = resp.headers.get("X-RateLimit-Credits-Required")
        if remaining is None or required is None:
            return
        try:
            if int(remaining) < int(required):
                raise CreditsExhaustedError(
                    f"rate limit credits exhausted "
                    f"(remaining={remaining}, required={required})"
                )
        except ValueError:
            # Malformed headers — log and proceed; don't fail on header parsing.
            logger.debug(
                "could not parse rate-limit headers: remaining={!r} required={!r}",
                remaining,
                required,
            )

    @staticmethod
    def _parse_retry_after(resp: requests.Response) -> int:
        raw = resp.headers.get("Retry-After", str(DEFAULT_RETRY_AFTER_S))
        try:
            return int(raw)
        except ValueError:
            return DEFAULT_RETRY_AFTER_S

    def _write_batch(self, records: list[dict], batch_index: int) -> None:
        # Server-side `select=` already narrowed the fields, but we defensively
        # filter again in case OpenAlex returns extras.
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

    settings = Settings()  # type: ignore[call-arg]  # pydantic reads from env
    downloader = OpenAlexDownloader(
        output_dir=args.output,
        filter_str=args.filter_str,
        api_key=settings.openalex_api_key,
    )
    try:
        downloader.run()
    except ValueError as exc:
        # Config errors (e.g. filter mismatch on resume) — user-facing, exit 1.
        logger.error(str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
