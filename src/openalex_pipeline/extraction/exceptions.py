"""Typed exceptions for the extraction module.

Two base classes group failures by origin so that ``__main__`` (and any future
orchestrator) can catch by category:

    ConnectorError   -- anything raised by the HTTP connector
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
    """


class RetryExhausted(ConnectorError):
    """A retryable status (5xx, 403) still failing after ``MAX_RETRIES``."""


class NonRetryableError(ConnectorError):
    """An HTTP error that retrying cannot fix: 301, 400, 404, or any other 4xx.

    The defining property of this category is simply that a retry is pointless
    -- the request itself, or the entity, is wrong. Contrast RetryExhausted,
    which covers transient statuses (5xx, 403) that were retried and still
    failed. The connector raises this immediately, without backoff.
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
