# Preliminary plan for repo structure

openalex-pipeline/
├── README.md
├── pyproject.toml
├── uv.lock
├── .env.example
├── .gitignore
├── .python-version
│
├── docs/ ...
│
├── openalex_pipeline/
│   ├── __init__.py
│   ├── definitions.py          # Dagster's entry point: top-level asset defs
│   ├── extraction/...
│   └── assets/                 # Dagster asset definitions
│      ├── __init__.py
│      ├── extraction.py       # @asset wrapping extraction.run()
│      └── loading.py          # future
│
├── dbt/                            # dbt project (sibling of src, NOT nested)
│   ├── dbt_project.yml
│   ├── profiles.yml                # gitignored if it has secrets; .example committed
│   ├── models/
│   │   ├── staging/
│   │   ├── intermediate/
│   │   └── marts/
│   ├── macros/
│   ├── tests/
│   └── seeds/
│
├── terraform/
│   ├── main.tf                     # GCP provider, project, region
│   ├── variables.tf
│   ├── outputs.tf
│   ├── gcs.tf                      # bucket for parquet landing
│   ├── bigquery.tf                 # dataset, possibly external tables
│   ├── iam.tf                      # service account, roles
│   └── terraform.tfvars.example    # committed; real .tfvars gitignored
│
├── dashboard/                      # Streamlit app
│   └── app.py
│
├── tests/
│   ├── __init__.py
│   ├── extraction/...
│   └── fixtures/
│       └── openalex_responses/     # canned JSON for HTTP-layer tests
│
├── data/                           # gitignored
│   └── raw/works/year=YYYY/...     # extraction output lives here
│
├── docker/
│   ├── Dockerfile                  # one image is enough for now
│   └── docker-compose.yml
│
└── scripts/                        # ad-hoc / dev convenience
    └── explore_openalex.py         # the exploratory notebook-as-script