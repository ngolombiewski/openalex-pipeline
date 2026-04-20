# SPECS.md

## Project

"AI Is Eating CS — But How Durable Is Its Research?" — DE Zoomcamp capstone. End-to-end batch data pipeline on OpenAlex data.

## Analytical Questions

1. **The Takeover** — How has AI's share of CS research grown over time?
2. **The Shelf Life** — Do AI papers age faster? (citation half-life by subfield)
3. **The Winner's Game** — Is citation impact more concentrated in AI than other CS subfields? (Gini coefficient)

## Data Source

OpenAlex works entity (~14.7 M CS works). Key gotchas:
- `cited_by_count` is cumulative, not time-resolved — half-life requires approximation
- Topics endpoint only, Concepts is deprecated
- Scale: filter to one year for development, full pull for production

## Pipeline Shape

OpenAlex CLI -> JSON -> Polars -> Parquet -> GCS -> BigQuery -> dbt -> Streamlit

Orchestrated by Dagster as software-defined assets.

## TECH STACK

See `docs/STACK.md`.

## Open Questions

- Exact OpenAlex subfield IDs for AI — needs exploration
- External vs. native BigQuery tables — try external first
- Citation half-life methodology — cohort-based approximation, document assumptions
- `dagster-dbt` native integration vs. shelling out — decide when wiring orchestration
