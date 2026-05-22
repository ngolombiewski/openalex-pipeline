from __future__ import annotations

import inspect

import pytest
import responses

from openalex_pipeline.extraction import connector
from openalex_pipeline.extraction.connector import fetch_page
from openalex_pipeline.extraction.exceptions import (
    DailyLimitReached,
    NonRetryableError,
    RetryExhausted,
)

QUERY = "works?filter=publication_year:1980&per_page=200"
API_KEY = "test-key"
URL = "https://api.openalex.org/works"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    # Disable backoff sleeps so retry tests stay fast.
    monkeypatch.setattr(connector, "sleep", lambda _: None)


def test_fetch_page_contract_signature() -> None:
    signature = inspect.signature(fetch_page)

    assert list(signature.parameters) == ["query", "cursor", "api_key"]
    assert signature.parameters["query"].annotation == "str"
    assert signature.parameters["cursor"].annotation == "str"
    assert signature.parameters["api_key"].annotation == "str"
    assert signature.return_annotation == "tuple[list[dict], str | None, int]"


@responses.activate
def test_fetch_page_returns_records_next_cursor_and_meta_count() -> None:
    responses.add(
        responses.GET,
        URL,
        json={
            "meta": {"count": 2, "next_cursor": "cursor-2"},
            "results": [{"id": "W1"}, {"id": "W2"}],
        },
        status=200,
    )

    records, next_cursor, count = fetch_page(QUERY, "*", API_KEY)

    assert records == [{"id": "W1"}, {"id": "W2"}]
    assert next_cursor == "cursor-2"
    assert count == 2

    actual_url = responses.calls[0].request.url
    assert actual_url is not None
    assert "filter=publication_year" in actual_url
    assert "api_key=test-key" in actual_url


@responses.activate
def test_fetch_page_normalizes_missing_next_cursor_to_none() -> None:
    responses.add(
        responses.GET,
        URL,
        json={"meta": {"count": 1}, "results": [{"id": "W1"}]},
        status=200,
    )

    _records, next_cursor, _count = fetch_page(QUERY, "*", API_KEY)

    assert next_cursor is None


@responses.activate
def test_fetch_page_normalizes_null_next_cursor_to_none() -> None:
    responses.add(
        responses.GET,
        URL,
        json={
            "meta": {"count": 1, "next_cursor": None},
            "results": [{"id": "W1"}],
        },
        status=200,
    )

    _records, next_cursor, _count = fetch_page(QUERY, "*", API_KEY)

    assert next_cursor is None


@responses.activate
def test_fetch_page_zero_result_year_returns_empty_tuple() -> None:
    responses.add(
        responses.GET,
        URL,
        json={"meta": {"count": 0}, "results": []},
        status=200,
    )

    assert fetch_page(QUERY, "*", API_KEY) == ([], None, 0)


@responses.activate
def test_fetch_page_raises_daily_limit_on_429() -> None:
    responses.add(responses.GET, URL, json={"error": "rate limit"}, status=429)

    with pytest.raises(DailyLimitReached):
        fetch_page(QUERY, "*", API_KEY)


@pytest.mark.parametrize("status", [301, 400, 404, 422])
@responses.activate
def test_fetch_page_raises_non_retryable_on_301_and_4xx_except_403_and_429(
    status: int,
) -> None:
    responses.add(responses.GET, URL, json={"error": "bad"}, status=status)

    with pytest.raises(NonRetryableError):
        fetch_page(QUERY, "*", API_KEY)


@responses.activate
def test_fetch_page_retries_5xx_then_succeeds() -> None:
    responses.add(responses.GET, URL, status=500)
    responses.add(responses.GET, URL, status=502)
    responses.add(
        responses.GET,
        URL,
        json={"meta": {"count": 1, "next_cursor": None}, "results": [{"id": "W1"}]},
        status=200,
    )

    records, next_cursor, count = fetch_page(QUERY, "*", API_KEY)

    assert records == [{"id": "W1"}]
    assert next_cursor is None
    assert count == 1
    assert len(responses.calls) == 3


@responses.activate
def test_fetch_page_retries_403_then_succeeds() -> None:
    responses.add(responses.GET, URL, status=403)
    responses.add(
        responses.GET,
        URL,
        json={"meta": {"count": 0}, "results": []},
        status=200,
    )

    assert fetch_page(QUERY, "*", API_KEY) == ([], None, 0)
    assert len(responses.calls) == 2


@responses.activate
def test_fetch_page_raises_retry_exhausted_after_max_retries_of_5xx() -> None:
    for _ in range(connector._MAX_RETRIES):
        responses.add(responses.GET, URL, status=500)

    with pytest.raises(RetryExhausted):
        fetch_page(QUERY, "*", API_KEY)

    assert len(responses.calls) == connector._MAX_RETRIES
