"""Configuration for one extraction run, sourced from environment variables.

The only module that holds runtime configuration. Everything else is a pinned
constant (see ``runner.SELECT_COLUMNS``, ``runner.PER_PAGE``) or a positional
function argument.

Required env vars (all prefixed ``OPENALEX_``):

  - ``OPENALEX_API_KEY``     -- OpenAlex API key. Credential; never logged,
                                never written to disk, never part of query
                                identity.
  - ``OPENALEX_FILTER``      -- Filter *expression* WITHOUT the
                                ``publication_year`` clause and WITHOUT the
                                ``filter=`` URL parameter name; the runner
                                owns both. Example:
                                ``primary_topic.field.id:17``.
  - ``OPENALEX_START_YEAR``  -- Inclusive lower bound (int).
  - ``OPENALEX_END_YEAR``    -- Inclusive upper bound (int).
  - ``OPENALEX_DATA_DIR``    -- Extraction root directory (Path).

A ``.env`` file in the working directory is auto-loaded (pydantic-settings
default). Process env vars take precedence over .env values.

Construct via ``Settings()`` -- pydantic-settings populates fields from env
on instantiation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Env-var-backed configuration for one extraction run."""

    model_config = SettingsConfigDict(
        env_prefix="OPENALEX_",
        env_file=".env",
        extra="ignore",
    )

    api_key: str
    filter: str
    start_year: int
    end_year: int
    data_dir: Path

    @model_validator(mode="after")
    def _years_in_order(self) -> Self:
        if self.start_year > self.end_year:
            raise ValueError(
                f"OPENALEX_START_YEAR ({self.start_year}) must be <= "
                f"OPENALEX_END_YEAR ({self.end_year})"
            )
        return self

    @property
    def years(self) -> list[int]:
        """Inclusive list of years ``[start_year, end_year]``."""
        return list(range(self.start_year, self.end_year + 1))
