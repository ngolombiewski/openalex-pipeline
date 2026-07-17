"""Immutable value types shared by orchestration metadata predicates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True, order=True)
class DbtRelationSpec:
    """Expected physical relation projected from one dbt model node."""

    name: str
    materialization: Literal["table", "view"]


@dataclass(frozen=True)
class WarehouseRelationMetadata:
    """Live BigQuery metadata for one expected dbt relation.

    ``modified`` is meaningful for tables only. A present view may report
    ``None`` because view timestamps do not participate in data freshness.
    """

    exists: bool
    modified: datetime | None
