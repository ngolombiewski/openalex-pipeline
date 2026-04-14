# openalex-pipeline

End-to-end data pipeline analyzing trends in Computer Science research using [OpenAlex](https://openalex.org), built as a capstone project for the [DE Zoomcamp](https://github.com/DataTalksClub/data-engineering-zoomcamp).

## The Question

**"AI Is Eating CS — But How Durable Is Its Research?"**

AI dominates CS publication volume. But does quantity mean impact? This project explores AI's growing share of CS research, whether AI papers age faster than work in other subfields, and how concentrated citation impact really is.

## Stack

OpenAlex CLI → Polars/Parquet → GCS → BigQuery → dbt → Streamlit, orchestrated by Dagster, provisioned with Terraform.

## Setup

*Coming soon.* See `SPECS.md` for project architecture.

## License

MIT
