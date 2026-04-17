# Planned directory structure for openalex-pipeline repo (suggested by Opus 4.6 given specs and stack)

openalex-pipeline/
├── CLAUDE.md
├── SPECS.md
├── STACK.md
├── pyproject.toml
├── docker-compose.yml
├── .env.example
├── docs/
│   └── openalex-llms.md
├── terraform/
│   ├── main.tf
│   ├── variables.tf
│   └── outputs.tf
├── pipeline/                  # Python package — ingestion + Dagster assets
│   ├── __init__.py
│   ├── assets/
│   │   ├── __init__.py
│   │   ├── ingest.py          # OpenAlex CLI → JSON → Parquet
│   │   ├── gcs.py             # Parquet → GCS
│   │   └── bigquery.py        # GCS → BQ external/native tables
│   ├── resources/
│   │   ├── __init__.py
│   │   └── io.py              # GCS client, BQ client configs
│   └── definitions.py         # Dagster Definitions entry point
├── dbt/
│   ├── dbt_project.yml
│   ├── profiles.yml           # or rely on env vars
│   ├── models/
│   │   ├── staging/
│   │   ├── intermediate/
│   │   └── marts/
│   └── macros/
├── dashboard/
│   └── app.py
├── data/                      # .gitignored, local exploration
│   └── raw/
├── scripts/                   # on-off helper scripts
└── notebooks/                 # .gitignored, scratch exploration

Key rationale: pipeline/ is both your Python package and your Dagster code location — definitions.py is what Dagster loads. dbt lives separately because dagster-dbt points at the dbt project path. Keeping them as siblings avoids circular weirdness.
