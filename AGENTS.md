# AGENTS.md

## Workflow

The workflow is always:

- Discuss the design.
- Spec it out.
- An agent implements.
- I review.

Don't proceed to implementation until I give the signal.

## Principles

These hold across the whole project. Each one earned its place; deviate only with discussion.

- **Filesystem as source of truth.** Pipeline state lives on disk. File presence and atomic rename are completion signals. No separate state stores.
- **Contracts before tests before implementation.** Pin the API in docstrings, write tests against those contracts, then implement.
- **Corruption is loud.** Known failure modes get typed exceptions; unknown failures propagate untouched. No silent recovery, no swallowed errors.
- **Explicit over inferred.** Schemas are pinned, not guessed. Defaults are stated, not implied.
- **Simplicity and specificity.** This is a pipeline-specific project, not a general-purpose toolkit. Prefer specific code over abstractions; YAGNI on configurability that isn't currently in use.
- **Trust the layer below within its scope.** Don't re-validate what an upstream layer has already asserted. Catch only what you can honestly diagnose.

## Execution Guidelines

- Use `uv`, never `pip`.
- Use `uv run ...`, never `python3` or `python`.
- Don't add dependencies; ask first if there is need. Everything in `pyproject.toml` is approved.
- See `.env.example` for available env vars.

## Docs

Read for any session:

- `ARCHITECTURE.md` — project overview, edit only when prompted.
- `STATE.md` — current project state, keep it up to date.

Read when relevant:

- `DATA_MODEL.md` — AI definition, bronze schema. Read when interacting with the data model.
- `PLAN.md` – Current high-level project plan with steps to be done.
- `docs/{layer}-design.md` — active design docs, more detailed than the general plan. Read when your work touches that layer.

Read only when explicitly prompted to:

- `docs/design-archive` — archived design docs, kept only for reference.
- `docs/openalex` — official OpenAlex docs.

Never search the web for documentation, unless explicitly asked to.
