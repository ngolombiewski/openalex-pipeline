# STACK.md

## Approved Tools

| Layer | Tool | Notes |
|---|---|---|
| Language | Python 3.12 | |
| Package manager | uv | Never pip |
| Data source | OpenAlex REST API | See `docs/openalex-llms.md` |
| Local processing | Polars, DuckDB | Never pandas |
| Cloud storage | GCS | |
| Warehouse | BigQuery | Partition by `publication_year`, cluster by `subfield_id` |
| Transforms | dbt-bigquery | See dbt docs |
| Orchestration | Dagster | Software-defined assets only, not ops/jobs |
| Dashboard | Streamlit | |
| IaC | Terraform | GCP provider |
| Containers | Docker, docker-compose | |

## uv

Already present deps in `pyproject.toml` are approved.

## direnv

Check `env.example` for present env vars, e.g.
- OPENALEX_API_KEY

## Not Approved

Anything not in the table above. Ask before introducing.
