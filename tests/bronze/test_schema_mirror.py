"""The bronze schema is declared twice; these tests assert the copies agree.

`BRONZE_SCHEMA` (Polars, written by the ingestion) and the pinned external-table
schema in `terraform/bigquery.tf` (read by BigQuery) describe the same Parquet
files. Nothing at runtime reconciles them: a divergence surfaces as a BigQuery
read error against already-uploaded data, long after the edit that caused it.

`publication_year` is deliberately absent from the Terraform declaration -- it
is supplied by the Hive partition key, and BigQuery rejects table creation when
a field appears in both the schema and the partition key.

The dbt side of the mirror is not asserted here. dbt consumes columns by name
and fails loudly at build time against the real external table, so it is
self-checking; these two declarations are the pair that can drift silently.
"""

from __future__ import annotations

from pathlib import Path
import re

import polars as pl
import pytest

from openalex_pipeline.bronze.schema import BRONZE_SCHEMA, NESTED_COLUMNS

TERRAFORM_BIGQUERY = Path(__file__).resolve().parents[2] / "terraform" / "bigquery.tf"

PARTITION_KEY_COLUMN = "publication_year"

POLARS_TO_BIGQUERY: dict[object, str] = {
    pl.String: "STRING",
    pl.Int64: "INTEGER",
    pl.Boolean: "BOOLEAN",
    pl.Float64: "FLOAT",
}

_SCHEMA_BLOCK = re.compile(r"schema\s*=\s*jsonencode\(\[(.*?)\]\)", re.DOTALL)
_FIELD = re.compile(
    r"\{\s*name\s*=\s*\"(?P<name>[^\"]+)\"\s*,"
    r"\s*type\s*=\s*\"(?P<type>[^\"]+)\"\s*,"
    r"\s*mode\s*=\s*\"(?P<mode>[^\"]+)\"\s*\}"
)


def terraform_schema() -> list[tuple[str, str, str]]:
    """Parse the pinned external-table schema as (name, type, mode) in order."""
    source = TERRAFORM_BIGQUERY.read_text(encoding="utf-8")
    block = _SCHEMA_BLOCK.search(source)
    assert block is not None, "no jsonencode schema block in terraform/bigquery.tf"
    fields = [
        (match["name"], match["type"], match["mode"])
        for match in _FIELD.finditer(block.group(1))
    ]
    assert fields, "schema block parsed but yielded no fields"
    return fields


@pytest.fixture(scope="module")
def declared() -> list[tuple[str, str, str]]:
    return terraform_schema()


def test_terraform_omits_the_partition_key(declared):
    """publication_year comes from the Hive partition key, never the schema."""
    assert PARTITION_KEY_COLUMN not in [name for name, _, _ in declared]


def test_column_sets_agree(declared):
    """Every bronze column except the partition key is declared, and vice versa."""
    expected = set(BRONZE_SCHEMA) - {PARTITION_KEY_COLUMN}
    assert {name for name, _, _ in declared} == expected


def test_column_order_agrees(declared):
    """Declaration order matches canonical bronze order, partition key removed."""
    expected = [name for name in BRONZE_SCHEMA if name != PARTITION_KEY_COLUMN]
    assert [name for name, _, _ in declared] == expected


def test_types_agree(declared):
    """Each declared BigQuery type is the mapping of its Polars dtype."""
    mismatched = {
        name: (declared_type, POLARS_TO_BIGQUERY[BRONZE_SCHEMA[name]])
        for name, declared_type, _ in declared
        if declared_type != POLARS_TO_BIGQUERY[BRONZE_SCHEMA[name]]
    }
    assert not mismatched


def test_every_dtype_has_a_mapping():
    """A new Polars dtype in the schema must state its BigQuery counterpart."""
    unmapped = {
        name: dtype
        for name, dtype in BRONZE_SCHEMA.items()
        if dtype not in POLARS_TO_BIGQUERY
    }
    assert not unmapped


def test_all_columns_nullable(declared):
    """Bronze imposes no NOT NULL; the external table must not either."""
    assert {mode for _, _, mode in declared} == {"NULLABLE"}


def test_nested_columns_are_declared_string(declared):
    """The eight nested fields land as raw JSON strings, so BigQuery sees STRING."""
    by_name = {name: declared_type for name, declared_type, _ in declared}
    assert {by_name[name] for name in NESTED_COLUMNS} == {"STRING"}


def test_nested_columns_are_a_subset_of_the_schema():
    """NESTED_COLUMNS names real bronze columns."""
    assert set(NESTED_COLUMNS) <= set(BRONZE_SCHEMA)
