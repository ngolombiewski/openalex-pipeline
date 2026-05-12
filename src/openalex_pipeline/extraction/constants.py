"""Module-level constants.

Single source of truth for operational defaults and the field selection (M10).
Importing these from anywhere else in the project is encouraged; redefining
them is not.
"""

from __future__ import annotations

OPENALEX_BASE_URL: str = "https://api.openalex.org"

# Default filter for production: all OpenAlex works whose primary topic
# is in the Computer Science field (field.id = 17). Override via
# OPENALEX_FILTER for dev/test pulls.
DEFAULT_FILTER: str = "primary_topic.field.id:17"

# Earliest publication year processed. Pre-1950 CS publications are
# negligible in volume (< few hundred per year in early decades) and
# treated as out of scope.
YEAR_FLOOR: int = 1950

# Field selection (M10): the set of fields requested via OpenAlex's
# `select` query parameter. Single source of truth, must stay in sync
# with docs/DATA_MODEL.md bronze schema. Changes here are deliberate
# schema changes, not configuration knobs.
SELECT_FIELDS: tuple[str, ...] = (
    "id",
    "title",
    "publication_year",
    "publication_date",
    "type",
    "language",
    "is_retracted",
    "is_paratext",
    "primary_topic",
    "topics",
    "cited_by_count",
    "counts_by_year",
    "cited_by_percentile_year",
    "citation_normalized_percentile",
    "fwci",
    "referenced_works_count",
    "open_access",
    "doi",
    "ids",
    "keywords",
    "updated_date",
)

# Name of the per-record timestamp field injected at write time (M9).
EXTRACTED_AT_FIELD: str = "_extracted_at"

# Per-year file names (treated as constants so the layout is grep-able).
META_FILENAME: str = "_META.json"
CURSOR_FILENAME: str = "_CURSOR"
SUCCESS_FILENAME: str = "_SUCCESS"

# Page file name pattern: page_NNNNN.jsonl, 5-digit zero-padded.
PAGE_FILENAME_TEMPLATE: str = "page_{number:05d}.jsonl"
PAGE_FILENAME_GLOB: str = "page_*.jsonl"

# Year directory pattern: year=YYYY/
YEAR_DIR_TEMPLATE: str = "year={year}"
