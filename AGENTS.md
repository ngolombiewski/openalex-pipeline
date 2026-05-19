# Rules

## Workflow

This is a learning project. The workflow is always:
- We discuss the design.
- We spec it out.
- Then you implement.
- I will review every line.
Don't proceed to implementation until I give the signal.

## Docs

Prefer local docs over web search. Check `docs/` first:
- `docs/SPECS.md` — Learn about the project.
- `docs/STACK.md` — Only use tools/deps approved here.
- `docs/DATA_MODEL.md` — Source of truth for all data modeling decisions.

## Execution Guidelines

- never `pip`, use `uv`
- use `uv run python` (or `uv run <script>`) instead of `python3` or `python` directly

## Current Status

- `docs/extraction-design.md` — Contains reasoning behind the extraction module design and explains its invariants
- `src/openalex_pipeline/extraction` – Extraction module implementation
- `tests/extraction` – Tests for extraction module

**Next steps**:
- Review extraction module for code quality and alignment with `SPECS.md` and `extraction-design.md`

## AGENT MEMORY

Your auto-memory feature is turned off. Append here everything that you feel you should remember in EVERY future session:
