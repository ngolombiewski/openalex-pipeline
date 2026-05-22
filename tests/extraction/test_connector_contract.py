from __future__ import annotations

import inspect

import pytest

from openalex_pipeline.extraction.connector import fetch_page


def test_fetch_page_contract_signature() -> None:
    signature = inspect.signature(fetch_page)

    assert list(signature.parameters) == ["query", "cursor", "api_key"]
    assert signature.parameters["query"].annotation == "str"
    assert signature.parameters["cursor"].annotation == "str"
    assert signature.parameters["api_key"].annotation == "str"
    assert signature.return_annotation == "tuple[list[dict], str | None, int]"


def test_fetch_page_is_still_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        fetch_page("works?filter=publication_year:1980", "*", "test-key")
