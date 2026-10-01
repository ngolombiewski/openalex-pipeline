"""Export the four production gold relations as the dashboard's frozen snapshot.

Run manually after a reviewed prod build has finished:

    uv run python tools/export_dashboard_snapshot.py --pipeline-revision <sha|unknown>

Reads `openalex_analytics` only; never runs dbt or writes to the warehouse.
Credentials are the caller's ADC impersonating the service account named by
OPENALEX_DBT_SERVICE_ACCOUNT, in project OPENALEX_GCP_PROJECT.

Writes one JSON array per relation plus `snapshot.json` into `dashboard/data/`.
All files are first written to a temporary sibling directory; the existing
directory is moved aside and the new one renamed into place, so a partial
snapshot is never at `dashboard/data/`. A crash between the two renames leaves
the directory absent, which the dashboard build rejects loudly.

The bound variables are read from `dbt/dbt_project.yml` with a narrow line
match rather than a YAML parser: they are top-level integer scalars under
`vars:`, and a missing or duplicated name raises.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "dashboard" / "data"
DBT_PROJECT = ROOT / "dbt" / "dbt_project.yml"

DATASET = "openalex_analytics"
LOCATION = "EU"
# Gold tables are a few thousand rows; 1 GiB per query only stops a mistake.
MAXIMUM_BYTES_BILLED = 1024**3
JS_MAX_SAFE_INTEGER = 2**53 - 1

BOUND_VARS = (
    "year_min",
    "year_max",
    "partial_year",
    "citation_age_year_min",
    "citation_age_year_max",
    "gini_cohort_min",
    "gini_citation_year_max",
)

_GINI_COLUMNS = (
    "citation_age",
    "n_papers",
    "total_citations",
    "zero_share",
    "gini",
    "gini_cited_only",
    "top1_share",
    "top5_share",
    "top10_share",
    "age0_citation_share",
    "zero_share_including_age0",
)


class ExportError(Exception):
    """A known export failure; the message names the relation and problem."""


@dataclass(frozen=True)
class Relation:
    name: str
    columns: tuple[str, ...]  # enforced gold contract columns, in contract order
    grain: tuple[str, ...]  # ORDER BY keys

    def query(self, project: str) -> str:
        return (
            f"SELECT {', '.join(self.columns)} "
            f"FROM `{project}.{DATASET}.{self.name}` "
            f"ORDER BY {', '.join(self.grain)}"
        )


RELATIONS = (
    Relation(
        "gold_ai_share_by_year",
        (
            "publication_year",
            "variant",
            "cs_works",
            "ai_works",
            "share",
            "is_partial_year",
        ),
        ("publication_year", "variant"),
    ),
    Relation(
        "gold_citation_age_by_year",
        (
            "citation_year",
            "cited_group",
            "citation_events",
            "cited_works",
            "p25_citation_age",
            "median_citation_age",
            "p75_citation_age",
            "share_age_lte_2",
            "share_age_lte_5",
            "share_age_lte_10",
        ),
        ("citation_year", "cited_group"),
    ),
    Relation(
        "gold_citation_gini_by_subfield",
        (
            "publication_year",
            "subfield_id",
            "subfield_display_name",
            "is_ai_strict",
            "is_ai_broad",
            *_GINI_COLUMNS,
        ),
        ("publication_year", "subfield_id", "citation_age"),
    ),
    Relation(
        "gold_citation_gini_by_group",
        ("publication_year", "cited_group", *_GINI_COLUMNS),
        ("publication_year", "cited_group", "citation_age"),
    ),
)


class QueryResult(Protocol):
    @property
    def schema(self) -> Sequence[Any]: ...  # items expose `.name`

    def __iter__(self) -> Any: ...  # yields mappings of column -> value


class Client(Protocol):
    """The subset of `google.cloud.bigquery.Client` the exporter uses."""

    def get_table(self, table: str) -> Any: ...  # result exposes `.modified`

    def query(self, query: str, job_config: Any = ...) -> Any: ...  # `.result()`


def read_bounds(dbt_project: Path) -> dict[str, int]:
    """Return the integer bound variables from `dbt_project.yml`.

    Raises `ExportError` if any name in `BOUND_VARS` is missing, duplicated, or
    not an integer literal.
    """
    text = dbt_project.read_text()
    bounds: dict[str, int] = {}
    for name in BOUND_VARS:
        matches = re.findall(rf"^\s+{name}:\s*(\S+)", text, flags=re.MULTILINE)
        if len(matches) != 1:
            raise ExportError(
                f"{dbt_project.name}: expected one {name!r}, found {len(matches)}"
            )
        try:
            bounds[name] = int(matches[0])
        except ValueError as exc:
            raise ExportError(
                f"{dbt_project.name}: {name!r} is not an integer"
            ) from exc
    return bounds


def fetch_relation(
    client: Client, project: str, relation: Relation
) -> list[dict[str, Any]]:
    """Run the relation's pinned query and return its rows as plain dicts.

    Raises `ExportError` if the result columns differ from the pinned list, the
    relation is empty, or an integer exceeds JavaScript's safe integer range.
    """
    from google.cloud import bigquery

    job_config = bigquery.QueryJobConfig(maximum_bytes_billed=MAXIMUM_BYTES_BILLED)
    result = client.query(relation.query(project), job_config=job_config).result()
    columns = tuple(field.name for field in result.schema)
    if columns != relation.columns:
        raise ExportError(
            f"{relation.name}: columns {columns} != pinned {relation.columns}"
        )
    rows = [{column: row[column] for column in relation.columns} for row in result]
    if not rows:
        raise ExportError(f"{relation.name}: relation is empty")
    for row in rows:
        for column, value in row.items():
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and abs(value) > JS_MAX_SAFE_INTEGER
            ):
                raise ExportError(
                    f"{relation.name}: {column}={value} exceeds JavaScript's safe integer range"
                )
    return rows


def check_bounds(
    rows: Mapping[str, list[dict[str, Any]]], bounds: Mapping[str, int]
) -> None:
    """Raise `ExportError` unless the exported data spans exactly the dbt bounds.

    Q1 spans year_min..year_max with is_partial_year true exactly on
    partial_year. Q2 spans citation_age_year_min..citation_age_year_max. Both
    Q3 relations span cohorts gini_cohort_min..gini_citation_year_max - 1 and
    reach exactly gini_citation_year_max as their last citation year.
    """

    def expect(relation: str, what: str, actual: object, expected: object) -> None:
        if actual != expected:
            raise ExportError(f"{relation}: {what} {actual} != dbt bound {expected}")

    q1 = rows["gold_ai_share_by_year"]
    years = [row["publication_year"] for row in q1]
    expect(
        "gold_ai_share_by_year",
        "publication years",
        (min(years), max(years)),
        (bounds["year_min"], bounds["year_max"]),
    )
    partial = {row["publication_year"] for row in q1 if row["is_partial_year"]}
    expect("gold_ai_share_by_year", "partial years", partial, {bounds["partial_year"]})

    q2_years = [row["citation_year"] for row in rows["gold_citation_age_by_year"]]
    expect(
        "gold_citation_age_by_year",
        "citation years",
        (min(q2_years), max(q2_years)),
        (bounds["citation_age_year_min"], bounds["citation_age_year_max"]),
    )

    for name in ("gold_citation_gini_by_subfield", "gold_citation_gini_by_group"):
        cohorts = [row["publication_year"] for row in rows[name]]
        expect(
            name,
            "cohorts",
            (min(cohorts), max(cohorts)),
            (bounds["gini_cohort_min"], bounds["gini_citation_year_max"] - 1),
        )
        last = max(row["publication_year"] + row["citation_age"] for row in rows[name])
        expect(name, "last citation year", last, bounds["gini_citation_year_max"])


def table_modified(client: Client, project: str) -> dict[str, datetime]:
    return {
        relation.name: client.get_table(f"{project}.{DATASET}.{relation.name}").modified
        for relation in RELATIONS
    }


def export_snapshot(
    client: Client,
    *,
    project: str,
    pipeline_revision: str,
    data_dir: Path = DATA_DIR,
    dbt_project: Path = DBT_PROJECT,
    now: datetime | None = None,
) -> None:
    """Export all relations and `snapshot.json` into `data_dir`, or nothing.

    Raises `ExportError` on a pinned-column mismatch, an empty relation, an
    unsafe integer, a bounds mismatch, or any relation's modification time
    changing during the export. Nothing is written unless every check passes.
    """
    if not pipeline_revision:
        raise ExportError("pipeline revision is empty; pass a revision or 'unknown'")
    bounds = read_bounds(dbt_project)
    exported_at = now or datetime.now(UTC)

    before = table_modified(client, project)
    rows = {
        relation.name: fetch_relation(client, project, relation)
        for relation in RELATIONS
    }
    after = table_modified(client, project)
    changed = sorted(name for name in before if before[name] != after[name])
    if changed:
        raise ExportError(
            f"{', '.join(changed)}: modified during export; rerun after the build"
        )

    check_bounds(rows, bounds)

    snapshot = {
        "exported_at": exported_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "source_tables": {
            relation.name: f"{project}.{DATASET}.{relation.name}"
            for relation in RELATIONS
        },
        "source_modified_at": {
            name: modified.astimezone(UTC).isoformat().replace("+00:00", "Z")
            for name, modified in before.items()
        },
        "pipeline_revision": pipeline_revision,
        "bounds": bounds,
        "row_counts": {
            name: len(relation_rows) for name, relation_rows in rows.items()
        },
    }
    files: dict[str, object] = {
        f"{name}.json": relation_rows for name, relation_rows in rows.items()
    }
    files["snapshot.json"] = snapshot
    _replace_directory(data_dir, files)


def _replace_directory(data_dir: Path, files: Mapping[str, object]) -> None:
    data_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".data-new-", dir=data_dir.parent))
    try:
        for filename, payload in files.items():
            text = json.dumps(payload, indent=1, ensure_ascii=False, allow_nan=False)
            (staging / filename).write_text(text + "\n")
    except BaseException:
        shutil.rmtree(staging)
        raise
    if data_dir.exists():
        retired = Path(tempfile.mkdtemp(prefix=".data-old-", dir=data_dir.parent))
        retired.rmdir()
        data_dir.rename(retired)
        staging.rename(data_dir)
        shutil.rmtree(retired)
    else:
        staging.rename(data_dir)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ExportError(f"environment variable {name} is not set")
    return value


def make_client(project: str, service_account: str) -> Client:
    """Build a BigQuery client from ADC impersonating `service_account`."""
    import google.auth
    from google.auth import impersonated_credentials
    from google.cloud import bigquery

    source, _ = google.auth.default()
    credentials = impersonated_credentials.Credentials(
        source_credentials=source,
        target_principal=service_account,
        target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    return bigquery.Client(project=project, credentials=credentials, location=LOCATION)


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Export production gold as the dashboard snapshot."
    )
    parser.add_argument(
        "--pipeline-revision",
        required=True,
        help="pipeline commit the reviewed results came from, or 'unknown'",
    )
    args = parser.parse_args(None if argv is None else list(argv))
    project = _require_env("OPENALEX_GCP_PROJECT")
    client = make_client(project, _require_env("OPENALEX_DBT_SERVICE_ACCOUNT"))
    export_snapshot(client, project=project, pipeline_revision=args.pipeline_revision)
    print(f"wrote snapshot to {DATA_DIR.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
