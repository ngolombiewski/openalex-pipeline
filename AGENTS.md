# Rules

## Workflow

This is a learning project. The workflow is always:
- Discuss the design.
- Spec it out.
- An agent implements.
- I will review every line.
Don't proceed to implementation until I give the signal.

## Docs

Prefer local docs (`docs/`) over web search.

- `docs/architecture.md` — Read this at the start of every session. Current project state: data model, module topology, data flows, contracts, configuration.
- `docs/plan.md` — Consult when starting work on a new module or feature. Contains open questions and prospective items not yet in the project state.
- `docs/adr/` — Consult only when questioning an existing decision. Immutable records of why decisions were made.

## Execution Guidelines

- use `uv`, never `pip`
- use `uv run`, never `python3` or `python`
- don't add dependencies, ask me first if there is need
- everything in `pyproject.toml` is approved