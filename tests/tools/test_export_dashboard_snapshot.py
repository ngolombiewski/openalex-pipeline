from __future__ import annotations

from datetime import UTC, datetime, timedelta
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "export_dashboard_snapshot.py"


def load_exporter():
    spec = importlib.util.spec_from_file_location(
        "export_dashboard_snapshot", MODULE_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


exporter = load_exporter()

DBT_PROJECT = """\
vars:
  year_min: 1950
  year_max: 1952
  partial_year: 1952
  citation_age_year_min: 2012
  citation_age_year_max: 2013
  gini_cohort_min: 2012
  gini_citation_year_max: 2014
"""
MODIFIED = datetime(2026, 7, 31, 12, tzinfo=UTC)


def gini_values(age: int) -> dict[str, Any]:
    return {
        "citation_age": age,
        "n_papers": 10,
        "total_citations": 20,
        "zero_share": 0.5,
        "gini": 0.8,
        "gini_cited_only": 0.6,
        "top1_share": 0.1,
        "top5_share": 0.3,
        "top10_share": 0.4,
        "age0_citation_share": 0.05,
        "zero_share_including_age0": 0.45,
    }


def valid_rows() -> dict[str, list[dict[str, Any]]]:
    q1 = [
        {
            "publication_year": year,
            "variant": variant,
            "cs_works": 100,
            "ai_works": 30,
            "share": 0.3,
            "is_partial_year": year == 1952,
        }
        for year in (1950, 1951, 1952)
        for variant in ("broad", "strict")
    ]
    q2 = [
        {
            "citation_year": year,
            "cited_group": "ai",
            "citation_events": 50,
            "cited_works": 20,
            "p25_citation_age": 2,
            "median_citation_age": 5,
            "p75_citation_age": 9,
            "share_age_lte_2": 0.25,
            "share_age_lte_5": 0.5,
            "share_age_lte_10": 0.8,
        }
        for year in (2012, 2013)
    ]
    cells = [(2012, 1), (2012, 2), (2013, 1)]
    subfield = [
        {
            "publication_year": cohort,
            "subfield_id": "https://openalex.org/subfields/1702",
            "subfield_display_name": "Artificial Intelligence",
            "is_ai_strict": True,
            "is_ai_broad": True,
            **gini_values(age),
        }
        for cohort, age in cells
    ]
    group = [
        {"publication_year": cohort, "cited_group": "ai", **gini_values(age)}
        for cohort, age in cells
    ]
    return {
        "gold_ai_share_by_year": q1,
        "gold_citation_age_by_year": q2,
        "gold_citation_gini_by_subfield": subfield,
        "gold_citation_gini_by_group": group,
    }


class FakeResult:
    def __init__(self, columns: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
        self.schema = [SimpleNamespace(name=column) for column in columns]
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class FakeClient:
    """Serves rows by relation name; `modified_after` simulates a build."""

    def __init__(
        self,
        rows: dict[str, list[dict[str, Any]]],
        *,
        columns: dict[str, tuple[str, ...]] | None = None,
        modified_after: dict[str, datetime] | None = None,
    ) -> None:
        self.rows = rows
        self.columns = columns or {}
        self.modified_after = modified_after or {}
        self.queries: list[str] = []

    def get_table(self, table: str) -> SimpleNamespace:
        name = table.rsplit(".", 1)[1]
        modified = self.modified_after.get(name, MODIFIED) if self.queries else MODIFIED
        return SimpleNamespace(modified=modified)

    def query(self, query: str, job_config: Any = None) -> SimpleNamespace:
        self.queries.append(query)
        relation = next(r for r in exporter.RELATIONS if f".{r.name}`" in query)
        columns: tuple[str, ...] = self.columns.get(relation.name) or relation.columns
        return SimpleNamespace(
            result=lambda: FakeResult(columns, self.rows[relation.name])
        )


@pytest.fixture
def paths(tmp_path: Path) -> dict[str, Path]:
    dbt_project = tmp_path / "dbt_project.yml"
    dbt_project.write_text(DBT_PROJECT)
    return {"data_dir": tmp_path / "dashboard" / "data", "dbt_project": dbt_project}


def run(client: FakeClient, paths: dict[str, Path], revision: str = "abc123") -> None:
    exporter.export_snapshot(
        client,
        project="proj",
        pipeline_revision=revision,
        data_dir=paths["data_dir"],
        dbt_project=paths["dbt_project"],
        now=datetime(2026, 10, 1, 9, tzinfo=UTC),
    )


def test_writes_relations_and_provenance(paths: dict[str, Path]) -> None:
    rows = valid_rows()
    client = FakeClient(rows)

    run(client, paths)

    data_dir = paths["data_dir"]
    assert sorted(p.name for p in data_dir.iterdir()) == sorted(
        [f"{name}.json" for name in rows] + ["snapshot.json"]
    )
    for name, expected in rows.items():
        assert json.loads((data_dir / f"{name}.json").read_text()) == expected
    snapshot = json.loads((data_dir / "snapshot.json").read_text())
    assert snapshot["exported_at"] == "2026-10-01T09:00:00Z"
    assert snapshot["pipeline_revision"] == "abc123"
    assert snapshot["source_tables"]["gold_ai_share_by_year"] == (
        "proj.openalex_analytics.gold_ai_share_by_year"
    )
    assert (
        snapshot["source_modified_at"]["gold_ai_share_by_year"]
        == "2026-07-31T12:00:00Z"
    )
    assert snapshot["bounds"]["gini_citation_year_max"] == 2014
    assert snapshot["row_counts"] == {name: len(r) for name, r in rows.items()}
    assert all("ORDER BY" in query for query in client.queries)
    assert not list(data_dir.parent.glob(".data-*"))


def test_unknown_revision_is_recorded_literally(paths: dict[str, Path]) -> None:
    run(FakeClient(valid_rows()), paths, revision="unknown")

    snapshot = json.loads((paths["data_dir"] / "snapshot.json").read_text())
    assert snapshot["pipeline_revision"] == "unknown"


def test_empty_revision_raises(paths: dict[str, Path]) -> None:
    with pytest.raises(exporter.ExportError, match="revision"):
        run(FakeClient(valid_rows()), paths, revision="")


def test_replaces_existing_snapshot_completely(paths: dict[str, Path]) -> None:
    data_dir = paths["data_dir"]
    data_dir.mkdir(parents=True)
    (data_dir / "stale.json").write_text("[]")

    run(FakeClient(valid_rows()), paths)

    assert not (data_dir / "stale.json").exists()
    assert (data_dir / "snapshot.json").exists()
    assert not list(data_dir.parent.glob(".data-*"))


def test_column_mismatch_raises_and_writes_nothing(paths: dict[str, Path]) -> None:
    relation = exporter.RELATIONS[0]
    client = FakeClient(valid_rows(), columns={relation.name: relation.columns[:-1]})

    with pytest.raises(exporter.ExportError, match=relation.name):
        run(client, paths)
    assert not paths["data_dir"].exists()


def test_empty_relation_raises(paths: dict[str, Path]) -> None:
    rows = valid_rows()
    rows["gold_citation_gini_by_group"] = []

    with pytest.raises(
        exporter.ExportError, match="gold_citation_gini_by_group: relation is empty"
    ):
        run(FakeClient(rows), paths)


def test_unsafe_integer_raises(paths: dict[str, Path]) -> None:
    rows = valid_rows()
    rows["gold_citation_age_by_year"][0]["citation_events"] = 2**53

    with pytest.raises(exporter.ExportError, match="citation_events"):
        run(FakeClient(rows), paths)
    assert not paths["data_dir"].exists()


def test_largest_safe_integer_and_booleans_pass(paths: dict[str, Path]) -> None:
    rows = valid_rows()
    rows["gold_citation_age_by_year"][0]["citation_events"] = 2**53 - 1

    run(FakeClient(rows), paths)

    q2 = json.loads((paths["data_dir"] / "gold_citation_age_by_year.json").read_text())
    assert q2[0]["citation_events"] == 2**53 - 1
    q1 = json.loads((paths["data_dir"] / "gold_ai_share_by_year.json").read_text())
    assert q1[-1]["is_partial_year"] is True


def test_modification_during_export_raises_and_writes_nothing(
    paths: dict[str, Path],
) -> None:
    client = FakeClient(
        valid_rows(),
        modified_after={"gold_citation_age_by_year": MODIFIED + timedelta(minutes=5)},
    )

    with pytest.raises(
        exporter.ExportError, match="gold_citation_age_by_year: modified"
    ):
        run(client, paths)
    assert not paths["data_dir"].exists()


@pytest.mark.parametrize(
    ("relation", "mutate", "message"),
    [
        (
            "gold_ai_share_by_year",
            lambda rows: [rows.pop(0), rows.pop(0)],
            "publication years",
        ),
        (
            "gold_ai_share_by_year",
            lambda rows: rows[0].update(is_partial_year=True),
            "partial-year flag",
        ),
        (
            "gold_ai_share_by_year",
            lambda rows: rows[-1].update(is_partial_year=False),
            "partial-year flag",
        ),
        (
            "gold_citation_age_by_year",
            lambda rows: rows.pop(),
            "citation years",
        ),
        (
            "gold_citation_gini_by_subfield",
            lambda rows: rows.pop(),
            "cohorts",
        ),
        (
            "gold_citation_gini_by_group",
            lambda rows: rows[-1].update(citation_age=2),
            "last citation year",
        ),
    ],
)
def test_bounds_mismatch_raises_and_writes_nothing(
    paths: dict[str, Path], relation: str, mutate: Any, message: str
) -> None:
    rows = valid_rows()
    mutate(rows[relation])

    with pytest.raises(exporter.ExportError, match=f"{relation}: {message}"):
        run(FakeClient(rows), paths)
    assert not paths["data_dir"].exists()


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (DBT_PROJECT.replace("  partial_year: 1952\n", ""), "found 0"),
        (DBT_PROJECT + "  year_min: 1960\n", "found 2"),
        (
            DBT_PROJECT.replace("year_max: 1952", 'year_max: "{{ env }}"'),
            "not an integer",
        ),
    ],
)
def test_unreadable_dbt_bounds_raise(
    paths: dict[str, Path], text: str, message: str
) -> None:
    paths["dbt_project"].write_text(text)

    with pytest.raises(exporter.ExportError, match=message):
        run(FakeClient(valid_rows()), paths)


def test_real_dbt_project_bounds_are_readable() -> None:
    bounds = exporter.read_bounds(exporter.DBT_PROJECT)

    assert set(bounds) == set(exporter.BOUND_VARS)


def test_pinned_columns_match_gold_contracts() -> None:
    gold_yml = (ROOT / "dbt" / "models" / "gold" / "_gold.yml").read_text()
    for relation in exporter.RELATIONS:
        block = gold_yml.split(f"  - name: {relation.name}\n", 1)[1].split(
            "\n  - name: ", 1
        )[0]
        columns = tuple(
            line.strip().removeprefix("- name: ")
            for line in block.splitlines()
            if line.startswith("      - name: ")
        )
        assert columns == relation.columns, relation.name
