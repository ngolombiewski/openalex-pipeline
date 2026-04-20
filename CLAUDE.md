# CLAUDE.md

## Project

"AI Is Eating CS — But How Durable Is Its Research?" — a batch data pipeline analyzing AI's growing share of CS research across three questions: how AI's share has grown over time, whether AI papers age faster (citation half-life by subfield), and whether citation impact is more concentrated in AI than other CS subfields (Gini coefficient). Data source: OpenAlex works entity.

## Working Mode

This is a solo learning project. For any concept central to the pipeline architecture — e.g. dbt modeling, Dagster asset graph, SQL transforms, BigQuery design — explain the approach before or alongside implementing it. For boilerplate and syntax, just do it.

## Docs

Prefer local docs over web search. Check `docs/` first:
- `docs/SPECS.md`
- `docs/STACK.md`
- `docs/DATA_MODEL.md` — Source of truth for all data modeling decisions.
- `docs//openalex-llms.md` — OpenAlex API reference for LLMs.

## TECH STACK

Before introducing any tool or library not already in use, consult `STACK.md` or ask. Hard constraints: never `pip` (use `uv`), never pandas (use Polars).
Always use `uv run python` (or `uv run <script>`) instead of `python3` or `python` directly.

## MEMORY (managed by Claude)

Your auto-memory feature is turned off. Append everything you need to remember at all times here:
