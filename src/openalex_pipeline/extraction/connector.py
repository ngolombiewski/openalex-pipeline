"""HTTP connector: the single OpenAlex API call plus retry/backoff.

This module is the primary test seam around the API. ``fetch_page`` is injected
into the worker as a callable (a closure in production), so tests substitute a
fake without any network.

Retry/backoff lives entirely inside ``fetch_page``. The worker sees only a
clean return or a typed raise -- never a raw HTTP status, never a partial
result.
"""

from __future__ import annotations


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

    The connector assembles the request URL as::

        https://api.openalex.org/{query}&cursor={cursor}   (+ api key param)

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
    raise NotImplementedError
