from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
import requests
import responses

from openalex_pipeline.extraction.config import Settings
from openalex_pipeline.extraction.constants import OPENALEX_BASE_URL, SELECT_FIELDS
from openalex_pipeline.extraction.errors import (
    BadRequest,
    CreditsExhausted,
    HTTPError,
    RateLimited,
    ServerError,
    TransientError,
)
from openalex_pipeline.extraction.http import _build_url, request_page
from openalex_pipeline.extraction.types import Page


WORKS_FILTER_1980 = "primary_topic.field.id:17,publication_year:1980"


def test_build_url_includes_required_openalex_query_parameters(settings: Settings) -> None:
    url = _build_url(
        settings,
        filter=WORKS_FILTER_1980,
        cursor="cursor value",
    )

    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == f"{OPENALEX_BASE_URL}/works"
    assert query["filter"] == [WORKS_FILTER_1980]
    assert query["cursor"] == ["cursor value"]
    assert query["per-page"] == [str(settings.per_page)]
    assert query["api_key"] == [settings.api_key]
    assert query["select"] == [",".join(SELECT_FIELDS)]


@responses.activate
def test_request_page_returns_page_for_successful_response(settings: Settings) -> None:
    responses.add(
        responses.GET,
        f"{OPENALEX_BASE_URL}/works",
        json={
            "meta": {"count": 2, "next_cursor": "next"},
            "results": [{"id": "W1"}, {"id": "W2"}],
        },
        status=200,
    )

    page = request_page(settings, WORKS_FILTER_1980, "*")

    assert page == Page(records=[{"id": "W1"}, {"id": "W2"}], meta_count=2, next_cursor="next")


@responses.activate
def test_request_page_allows_valid_zero_result_page(settings: Settings) -> None:
    responses.add(
        responses.GET,
        f"{OPENALEX_BASE_URL}/works",
        json={"meta": {"count": 0, "next_cursor": None}, "results": []},
        status=200,
    )

    page = request_page(settings, WORKS_FILTER_1980, "*")

    assert page == Page(records=[], meta_count=0, next_cursor=None)


@responses.activate
def test_request_page_retries_transient_status_then_returns_successful_page(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    responses.add(responses.GET, f"{OPENALEX_BASE_URL}/works", json={}, status=500)
    responses.add(
        responses.GET,
        f"{OPENALEX_BASE_URL}/works",
        json={
            "meta": {"count": 1, "next_cursor": None},
            "results": [{"id": "W1"}],
        },
        status=200,
    )

    page = request_page(settings, WORKS_FILTER_1980, "*")

    assert page == Page(records=[{"id": "W1"}], meta_count=1, next_cursor=None)
    assert len(responses.calls) == 2


@responses.activate
def test_request_page_raises_credits_exhausted_without_retry(settings: Settings) -> None:
    responses.add(responses.GET, f"{OPENALEX_BASE_URL}/works", json={}, status=429)

    with pytest.raises(CreditsExhausted):
        request_page(settings, WORKS_FILTER_1980, "*")

    assert len(responses.calls) == 1


@responses.activate
def test_request_page_raises_bad_request_without_retry(settings: Settings) -> None:
    responses.add(responses.GET, f"{OPENALEX_BASE_URL}/works", json={}, status=400)

    with pytest.raises(BadRequest):
        request_page(settings, WORKS_FILTER_1980, "*")

    assert len(responses.calls) == 1


@pytest.mark.parametrize(
    ("status", "expected_error"),
    [
        (403, RateLimited),
        (500, ServerError),
        (503, ServerError),
    ],
)
@responses.activate
def test_request_page_retries_transient_statuses_then_raises(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    status: int,
    expected_error: type[Exception],
) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    for _ in range(settings.max_retries + 1):
        responses.add(responses.GET, f"{OPENALEX_BASE_URL}/works", json={}, status=status)

    with pytest.raises(expected_error):
        request_page(settings, WORKS_FILTER_1980, "*")

    assert len(responses.calls) == settings.max_retries + 1


@responses.activate
def test_request_page_retries_timeout_then_raises(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    for _ in range(settings.max_retries + 1):
        responses.add(
            responses.GET,
            f"{OPENALEX_BASE_URL}/works",
            body=requests.exceptions.Timeout("timed out"),
        )

    with pytest.raises(TransientError):
        request_page(settings, WORKS_FILTER_1980, "*")

    assert len(responses.calls) == settings.max_retries + 1


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"meta": {"count": 1}},
        {"results": [{"id": "W1"}]},
        {"meta": {"next_cursor": None}, "results": []},
    ],
)
@responses.activate
def test_request_page_raises_http_error_for_malformed_success_body(
    settings: Settings,
    body: dict,
) -> None:
    responses.add(responses.GET, f"{OPENALEX_BASE_URL}/works", json=body, status=200)

    with pytest.raises(HTTPError):
        request_page(settings, WORKS_FILTER_1980, "*")
