# CLAUDE.md — Agent Context

## Project

**"AI Is Eating CS — But How Durable Is Its Research?"**
DE Zoomcamp capstone project. End-to-end batch data pipeline analyzing AI's growing share of CS research, citation longevity, and impact concentration using OpenAlex data.

## Owner Context

- Math MSc (deep learning thesis), strong on theory, building DE skills
- First time using Dagster, dbt, Terraform, and agentic AI tooling
- Wants to **own the logic** — AI handles boilerplate, configs, syntax; human owns architecture decisions and validates everything
- If something is a core learning concept (dbt modeling, Dagster asset graph design, SQL transforms), explain it rather than just generating it

## Tech Stack

| Layer | Tool |
|---|---|
| Language | Python 3.12 |
| Data source | OpenAlex API (works entity only, via CLI + REST) |
| Ingestion | `openalex-official` CLI → JSON → Polars → Parquet |
| Local processing | Polars, DuckDB |
| Cloud storage | GCS (data lake) |
| Warehouse | BigQuery |
| Transforms | dbt (dbt-bigquery) |
| Orchestration | Dagster |
| Dashboard | Streamlit |
| IaC | Terraform (GCP) |
| Package management | uv |
| Containers | Docker, docker-compose |
| OS | Pop!_OS (Ubuntu-based), zsh, GNOME Terminal |

## Repository Structure (target)

```
capstone/
├── CLAUDE.md              # this file
├── SPECS.md               # project specification
├── Makefile
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── docs/
│   ├── openalex-llms.txt  # local copy of API reference
│   └── data-dictionary.md # fields we actually use, with notes
├── terraform/
│   ├── main.tf
│   ├── variables.tf
│   └── outputs.tf
├── dagster/
│   ├── definitions.py
│   ├── assets/
│   ├── resources/
│   └── io_managers/
├── dbt/
│   ├── dbt_project.yml
│   ├── models/
│   │   ├── staging/
│   │   ├── intermediate/
│   │   └── marts/
│   └── tests/
├── scripts/               # one-off / utility scripts
├── notebooks/             # exploration only, not part of pipeline
├── streamlit/
│   └── app.py
└── tests/
```

## Coding Conventions

- **Formatter/linter**: ruff (format + lint)
- **Type hints**: yes, for all function signatures
- **Docstrings**: Google style, but only where non-obvious
- **Naming**: snake_case everywhere (Python, SQL, file names)
- **SQL style (dbt)**: lowercase keywords, CTEs over subqueries, one column per line in SELECT
- **Dagster**: software-defined assets, not ops/jobs where possible
- **Error handling**: fail loud in pipeline code; no silent swallows
- **Secrets**: never committed; use environment variables or .env (gitignored)
- **Git**: conventional commits (feat:, fix:, docs:, etc.)

## Key Decisions (append as project evolves)

- Works entity only (no authors/institutions) — sufficient for the analytical questions, keeps scope manageable
- OpenAlex CLI for bulk download (metadata only, no PDFs)
- Topic hierarchy (field → subfield → topic) extracted from `primary_topic` nested object — this becomes a dimension table in dbt
- Partition BigQuery by `publication_year`, cluster by `subfield_id`

## Data Notes

- OpenAlex CLI outputs one JSON file per work in flat or nested directory structure
- We need: `id`, `publication_year`, `cited_by_count`, `type`, `primary_topic` (contains `.id`, `.display_name`, `.subfield`, `.field`, `.domain`), `open_access.is_oa`
- Filter: `topics.subfield.id` for CS subfields, or `topics.field.id` for the CS field
- ~20M works in CS — will likely need to sample or filter by year range for development, full pull for production
- `cited_by_count` is cumulative and not time-resolved — citation half-life will need to be approximated or use the `cited_by_percentile_year` fields if available
- Concepts endpoint is deprecated; use Topics

## What NOT to do

- Do not use pip — use `uv add` for dependencies, `uv run` for execution
- Do not use Airflow, Prefect, or Kestra — we use Dagster
- Do not use pandas for dataframe operations — use Polars
- Do not create dbt models that reference the deprecated `concepts` field
- Do not over-engineer: this is a capstone, not a production system. Good enough > perfect.

## Reference Docs

- OpenAlex API: `docs/openalex-llms.txt` (local copy — use this first, web search only if insufficient)
- OpenAlex CLI: `uv add openalex-official`, see https://pypi.org/project/openalex-official/
- Dagster: https://docs.dagster.io
- dbt: https://docs.getdbt.com
- Polars: https://docs.pola.rs
- Terraform GCP: https://registry.terraform.io/providers/hashicorp/google/latest/docs
