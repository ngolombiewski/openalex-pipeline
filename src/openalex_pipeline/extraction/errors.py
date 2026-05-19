"""Exception hierarchy for the extraction module.

The HTTP layer raises typed exceptions; the runner decides what to do about
each. See docs/extraction-design.md § Error Taxonomy for the policy table.

Design note: errors travel as exceptions, never as sentinel return values.
A function either returns a valid result or raises. This is a structural
defense against the silent-skip bug class that plagued the official CLI.
"""

from __future__ import annotations


class ExtractionError(Exception):
    """Base class for all extraction-module exceptions."""


# --- HTTP-layer exceptions (raised by extraction.http.request_page) ---


class HTTPError(ExtractionError):
    """Base for HTTP-layer failures."""


class CreditsExhausted(HTTPError):
    """OpenAlex returned 429: assumed daily credit limit reached.

    Treated by the runner as a clean stop signal (return summary with
    stopped_reason="credits_exhausted", exit 0). Not retryable within
    the same run; resume tomorrow. This mapping is based on current EDA and
    may be adjusted if production API behavior differs.
    """


class RateLimited(HTTPError):
    """OpenAlex returned 403: assumed sub-second burst rate limit.

    Transient. request_page() retries with exponential backoff internally.
    Only escapes if max_retries is exhausted, in which case it propagates
    as fatal. This mapping is based on current EDA and may be adjusted if
    production API behavior differs.
    """


class ServerError(HTTPError):
    """OpenAlex returned 5xx.

    Same retry semantics as RateLimited: transient, retried internally,
    only escapes if max_retries is exhausted.
    """


class TransientError(HTTPError):
    """Network-layer failure (timeout, connection reset, DNS, etc.).

    Same retry semantics as RateLimited and ServerError.
    """


class BadRequest(HTTPError):
    """OpenAlex returned 400. Configuration bug; never retried.

    Indicates a malformed filter, unknown field, or similar caller error.
    Fail loudly.
    """


# --- Logic-layer exceptions (raised by scan/storage/runner) ---


class DriftDetected(ExtractionError):
    """M6 violation: API meta.count differs from _META.json.expected_count.

    Raised at resume time, on the first response after restart. Caught by
    the runner, which discards the year directory via storage.discard_year()
    and restarts the year from scratch within the same run. A second drift
    on the same year propagates as fatal.

    Attributes:
        year: the publication year for which drift was detected.
        expected: the expected_count recorded in _META.json.
        observed: the meta.count returned by the API on resume.
    """

    def __init__(self, year: int, expected: int, observed: int) -> None:
        super().__init__(
            f"Drift detected for year {year}: "
            f"expected {expected} records, API reports {observed}"
        )
        self.year = year
        self.expected = expected
        self.observed = observed


class ReconciliationFailed(ExtractionError):
    """M7 violation: end-of-year record count != _META.json.expected_count.

    Propagates as fatal; no _SUCCESS marker is written. Manual intervention
    required.

    Attributes:
        year: the publication year that failed reconciliation.
        expected: the expected_count recorded in _META.json.
        observed: the actual count of records summed across page files.
    """

    def __init__(self, year: int, expected: int, observed: int) -> None:
        super().__init__(
            f"Reconciliation failed for year {year}: "
            f"expected {expected} records, found {observed} on disk"
        )
        self.year = year
        self.expected = expected
        self.observed = observed


class FilterScopeMismatch(ExtractionError):
    """M8 violation: a completed year was fetched with a different filter.

    Propagates as fatal. Refuses to mix data from different filter scopes
    in the same output directory.

    Attributes:
        year: the publication year with the mismatched filter.
        expected: the current run's effective per-year API filter.
        observed: the filter recorded in the year's _META.json.
    """

    def __init__(self, year: int, expected: str, observed: str) -> None:
        super().__init__(
            f"Filter scope mismatch for year {year}: "
            f"current run uses {expected!r}, but year was fetched with {observed!r}"
        )
        self.year = year
        self.expected = expected
        self.observed = observed


class CorruptedYearState(ExtractionError):
    """M2/M3/M4 violation: a year directory is in an inconsistent state.

    Raised by scan() when it encounters an in-progress year that cannot be
    cleanly resumed and should not be automatically discarded.

    Recoverable crash states such as orphan _META.json, orphan page files,
    or a missing _CURSOR are returned by scan() as RecoverableYearState
    inside ResumePlan. scan() remains read-only; run() performs any discard.

    M4 page-numbering gaps are fatal and use this exception. They signal
    tampering or filesystem corruption we don't understand.

    Attributes:
        year: the publication year with the corruption.
        reason: human-readable description of the specific violation.
    """

    def __init__(self, year: int, reason: str) -> None:
        super().__init__(f"Corrupted state for year {year}: {reason}")
        self.year = year
        self.reason = reason
