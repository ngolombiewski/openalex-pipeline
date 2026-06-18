"""HTTP connector: the single OpenAlex API call plus retry/backoff.

This module is the primary test seam around the API. ``fetch_page`` is injected
into the worker as a callable (a closure in production), so tests substitute a
fake without any network.

Retry/backoff lives entirely inside ``fetch_page``. The worker sees only a
clean return or a typed raise -- never a raw HTTP status, never a partial
result.
"""

from __future__ import annotations

from time import sleep
from typing import Final

from loguru import logger
import requests

from .exceptions import DailyLimitReached, NonRetryableError, RetryExhausted

_BASE_URL = "https://api.openalex.org"
_TIMEOUT_SECONDS: Final = 30.0
_MAX_RETRIES: Final = 5
_INITIAL_BACKOFF_SECONDS: Final = 1.0
_BACKOFF_FACTOR: Final = 2.0


def fetch_page(
    query: str,
    cursor: str,
    api_key: str,
) -> tuple[list[dict], str | None, int]:
    """Fetch one page of OpenAlex ``works`` results.

    Args:
        query:   The query string, minus the ``https://api.openalex.org/``
                 host prefix, cursor, and API key -- exactly as stored in
                 _META.json. Treated as opaque; never parsed.
        cursor:  The pagination cursor. ``"*"`` for the first page of a year.
        api_key: OpenAlex API key. A credential, passed separately and never
                 written to disk / never part of query identity.

    The connector assembles the request as::

        GET https://api.openalex.org/{query}
            ?cursor=<url-encoded>&api_key=<url-encoded>

    Returns:
        A tuple ``(records, next_cursor, meta_count)``:
          - records:    list[dict], the response ``results`` array, parsed but
                        otherwise untouched (no model, no validation).
          - next_cursor: str, or None when the API returns no further cursor
                        (last page).
          - meta_count: int, the response ``meta.count``. Returned on every
                        call though only the first page's value is used.

        ``([], None, 0)`` is a valid return: a query matching zero works.

    Raises:
        DailyLimitReached: HTTP 429. Clean daily stop; propagated untouched by
                           the worker and caught by the runner.
        RetryExhausted:    HTTP 5xx or 403 still failing after ``MAX_RETRIES``
                           exponential-backoff attempts.
        NonRetryableError:       HTTP 301, 400, 404, or any other 4xx -- non-retryable.

    The connector raises only at fetch time; there is no in-flight on-disk
    state to clean up.
    """
    url = f"{_BASE_URL}/{query}"
    params = {"api_key": api_key, "cursor": cursor}

    last_failure: str | None = None
    backoff = _INITIAL_BACKOFF_SECONDS

    for attempt in range(_MAX_RETRIES):
        try:
            response = requests.get(url, params=params, timeout=_TIMEOUT_SECONDS)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_failure = f"network error: {exc!r}"
        else:
            status = response.status_code
            if status == 200:
                try:
                    data = response.json()
                    if not isinstance(data, dict):
                        raise TypeError(f"top-level JSON is {type(data).__name__}")
                    meta = data["meta"]
                    if not isinstance(meta, dict):
                        raise TypeError(f"meta is {type(meta).__name__}")
                    return (
                        data["results"],
                        meta.get("next_cursor"),
                        meta["count"],
                    )
                except (ValueError, KeyError, TypeError) as exc:
                    raise NonRetryableError(
                        f"malformed 200 response: {exc!r}; body={response.text[:200]!r}"
                    ) from exc
            if status == 429:
                raise DailyLimitReached(
                    f"HTTP 429 daily limit reached at cursor={cursor!r}"
                )
            # 301 or any 4xx other than 403 -> non-retryable.
            if status == 301 or (400 <= status < 500 and status != 403):
                raise NonRetryableError(
                    f"HTTP {status} for cursor={cursor!r}: {response.text[:200]}"
                )
            # 403 or 5xx -> retryable. 403 is OpenAlex's burst rate-limit
            # response (verified empirically on sub-second bursts, and per the
            # API docs), not an auth failure -- backoff is the right treatment.
            last_failure = f"HTTP {status}"

        if attempt + 1 < _MAX_RETRIES:
            logger.warning(
                "fetch attempt {}/{} failed ({}); retrying in {:.1f}s",
                attempt + 1,
                _MAX_RETRIES,
                last_failure,
                backoff,
            )
            sleep(backoff)
            backoff *= _BACKOFF_FACTOR

    raise RetryExhausted(
        f"exhausted {_MAX_RETRIES} retries; last failure: {last_failure}"
    )
