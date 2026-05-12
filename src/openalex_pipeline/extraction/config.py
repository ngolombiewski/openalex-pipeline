"""Runtime configuration loaded from environment variables.

Settings is structurally a class because pydantic-settings requires it,
but it is a pure data object — no operational state, no business logic
beyond validation and one derivation method.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from extraction.constants import DEFAULT_FILTER, YEAR_FLOOR


class Settings(BaseSettings):
    """Configuration loaded once from environment variables.

    All values can be overridden via OPENALEX_* environment variables.
    See docs/extraction-design.md § Configuration Surface for the full table.

    Attributes:
        api_key: OpenAlex API key (required). Authenticates all requests.
        output_dir: root of the output tree. Year directories are created
            beneath this.
        filter: filter string passed to the OpenAlex API (without the
            "filter=" prefix). For dev/test, override to narrow the pull;
            for production, the default selects all CS works.
        year_range: optional year-range override. Accepts a single year
            ("2024") or an inclusive span ("1980-2025"). When None, the
            range is YEAR_FLOOR to the current year inclusive.
        per_page: page size for OpenAlex requests. Max 200.
        max_retries: number of retries for transient errors (403, 5xx,
            timeouts) before propagating as fatal.
        log_level: loguru log level (e.g. "INFO", "DEBUG").
    """

    api_key: str
    output_dir: Path = Path("data/raw/works")
    filter: str = DEFAULT_FILTER
    year_range: str | None = None
    per_page: int = 200
    max_retries: int = 5
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_prefix="OPENALEX_",
        env_file=".env",
        extra="ignore",
    )

    def resolved_year_range(self) -> range:
        """Return the years to process, as a Python range (start inclusive,
        end exclusive — call list() or iterate normally).

        Resolution rules:
        - year_range is None → range(YEAR_FLOOR, current_year + 1).
        - year_range is a single year like "2024" → range(2024, 2025).
        - year_range is a span like "1980-2025" → range(1980, 2026).

        The current year is evaluated at call time (datetime.now().year),
        not at Settings construction; this allows long-running tools to
        pick up new years as they begin.

        Raises:
            ValueError: year_range is malformed or specifies years outside
                [YEAR_FLOOR, current_year].
        """
        ...
