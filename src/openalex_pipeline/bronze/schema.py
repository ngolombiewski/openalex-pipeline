"""Bronze schema constants.

A leaf module: depends on nothing but Polars. Both ``core`` and ``manifest``
import from here.
"""

from __future__ import annotations

import polars as pl


BRONZE_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "id": pl.String,
    "title": pl.String,
    "publication_year": pl.Int64,
    "publication_date": pl.String,
    "type": pl.String,
    "language": pl.String,
    "is_retracted": pl.Boolean,
    "is_paratext": pl.Boolean,
    "primary_topic": pl.String,
    "topics": pl.String,
    "cited_by_count": pl.Int64,
    "counts_by_year": pl.String,
    "cited_by_percentile_year": pl.String,
    "citation_normalized_percentile": pl.String,
    "fwci": pl.Float64,
    "referenced_works_count": pl.Int64,
    "open_access": pl.String,
    "doi": pl.String,
    "ids": pl.String,
    "keywords": pl.String,
    "updated_date": pl.String,
}
"""The 21-column bronze schema. Imposed on read; no schema inference is used.

Column order is the canonical bronze column order. The eight nested columns
(primary_topic, topics, counts_by_year, cited_by_percentile_year,
citation_normalized_percentile, open_access, ids, keywords) are pl.String
holding raw verbatim JSON, exactly as OpenAlex emitted it. They are parsed
downstream in dbt staging, not here.

The scalar dtypes are load-bearing for integrity: a scalar whose value does not
conform to its dtype raises a Polars ComputeError on read. Scalar
type-conformance is therefore a read-time invariant, not a separate check.

publication_date and updated_date are deliberately pl.String, not pl.Date: date
typing is deferred to dbt staging.
"""

NESTED_COLUMNS: tuple[str, ...] = (
    "primary_topic",
    "topics",
    "counts_by_year",
    "cited_by_percentile_year",
    "citation_normalized_percentile",
    "open_access",
    "ids",
    "keywords",
)
"""The eight columns landed as raw JSON strings. Subset of BRONZE_SCHEMA keys."""
