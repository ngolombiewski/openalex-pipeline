"""Typed exceptions for the extraction module.

Two base classes group failures by origin so that ``__main__`` (and any future
orchestrator) can catch by category:

    ConnectorError   -- anything wrong with the API exchange. Raised by the
                        connector, except EmptyPageAnomaly, which the worker
                        raises (cross-page anomalies are only visible there).
    StorageError     -- anything raised by the storage layer

``DailyLimitReached`` is deliberately a plain ``ConnectorError`` and *not* a
kind of ``HardFailure``: it is a clean, expected daily stop, not an error
condition. The runner catches it as a normal stop path so it can return a
partial run report.
"""


class ConnectorError(Exception):
    """Base for all HTTP connector failures."""


class DailyLimitReached(ConnectorError):
    """HTTP 429 -- daily free-credit budget exhausted.

    Expected roughly once per day. Raised by the connector, propagated
    untouched by the worker, and caught by the runner so it can return a
    partial run report. Resume the next day.

    429 is specifically the daily cap, not the burst limiter: OpenAlex signals
    per-second burst overruns with 403 (see RetryExhausted), so mapping every
    429 to a clean daily stop is sound.
    """


class RetryExhausted(ConnectorError):
    """A retryable status (5xx, 403) still failing after ``MAX_RETRIES``.

    403 is retryable because it is OpenAlex's burst rate-limit response
    (verified empirically on sub-second async bursts, and per the API docs),
    not an auth failure. Contrast 429, the daily cap (DailyLimitReached).
    """


class NonRetryableError(ConnectorError):
    """An HTTP error that retrying cannot fix: 301, 400, 404, or any other 4xx.

    The defining property of this category is simply that a retry is pointless
    -- the request itself, or the entity, is wrong. Contrast RetryExhausted,
    which covers transient statuses (5xx, 403) that were retried and still
    failed. The connector raises this immediately, without backoff.
    """


class EmptyPageAnomaly(ConnectorError):
    """The API returned an empty results page where one must not occur.

    Raised by the worker, before anything is written to disk, when an empty
    page arrives WITH a live next_cursor -- mid-stream or as the first page.
    Not anomalous (and not this exception): an empty page with no cursor,
    which is either a legitimate zero-result year (first page) or a trailing
    empty page (the worker skips the write and finalizes).

    This is what makes extraction's promise explicit: the only possibly
    zero-byte page file is page-0001 of a zero-result year. Bronze asserts
    exactly that promise when it rejects zero-byte pages in multi-page years.
    Because nothing is written, the year stays resumable at the same cursor;
    a rerun retries it, and a persistent anomaly fails loudly every run.
    """


class StorageError(Exception):
    """Base for all storage-layer failures."""


class CorruptedState(StorageError):
    """A year directory holds a file combination that is not FRESH,
    IN_PROGRESS, or COMPLETE.

    The module does not guard against external tampering, but any classification
    ambiguity or blatant inconsistency is surfaced loudly rather than recovered
    from silently.
    """


class QueryMismatch(StorageError):
    """The stored query for an existing year does not equal the current run's
    canonical query.

    Mixing data from different queries/filters corrupts the dataset, so this is
    always a loud failure.
    """
