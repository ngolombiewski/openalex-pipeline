from __future__ import annotations

import pytest

from openalex_pipeline.extraction import __main__ as extraction_main
from openalex_pipeline.extraction.types import RunSummary


@pytest.mark.parametrize("stopped_reason", ["all_complete", "credits_exhausted"])
def test_main_returns_zero_for_clean_stop_reasons(
    monkeypatch: pytest.MonkeyPatch,
    stopped_reason: str,
) -> None:
    # The CLI wrapper should keep the runner's policy visible: both a fully
    # complete run and an expected daily-credit stop are successful exits.
    class StubSettings:
        pass

    def stub_run(_settings: StubSettings) -> RunSummary:
        return RunSummary(
            years=[],
            stopped_reason=stopped_reason,
            total_records_fetched=0,
        )

    monkeypatch.setattr(extraction_main, "Settings", StubSettings, raising=False)
    monkeypatch.setattr(extraction_main, "run", stub_run, raising=False)

    assert extraction_main.main() == 0
