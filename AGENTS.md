# Rules

## Workflow

This is a learning project. The workflow is always:
- Discuss the design.
- Spec it out.
- An agent implements.
- I will review every line.
Don't proceed to implementation until I give the signal.

## Docs

Prefer local docs over web search. Check `docs/` first:
- `docs/SPECS.md` — Learn about the project.
- `docs/DATA_MODEL.md` — Source of truth for all data modeling decisions.

## Execution Guidelines

- use `uv`, never `pip`
- use `uv run ...`, never `python3` or `python`
- don't add dependencies, ask me first if there is need
- everything in `pyproject.toml` is approved
- see `env.example` for available env vars

## Current Status

Designing the extraction module, destinations:
- `src/openalex_pipeline/extraction`
- `tests/extraction`

## AGENT MEMORY

Your auto-memory feature is turned off. Append here everything that you feel you should remember in EVERY future session:
