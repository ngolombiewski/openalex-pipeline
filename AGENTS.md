# AGENTS.md

## Workflow

The workflow is always:

- Discuss the design.
- Spec it out.
- An agent implements.
- I review.

Don't proceed to implementation until I give the signal.

## Principles

These hold across the whole project. Each one earned its place; deviate only
with discussion.

- **Filesystem as source of truth.** Pipeline state lives on disk. File presence
  and atomic rename are completion signals. No separate state stores.
- **Contracts before tests before implementation.** Pin the API in docstrings,
  write tests against those contracts, then implement.
- **Corruption is loud.** Known failure modes get typed exceptions; unknown
  failures propagate untouched. No silent recovery, no swallowed errors.
- **Explicit over inferred.** Schemas are pinned, not guessed. Defaults are
  stated, not implied.
- **Simplicity and specificity.** This is a pipeline-specific project, not a
  general-purpose toolkit. Prefer specific code over abstractions; YAGNI on
  configurability that isn't currently in use.
- **Trust the layer below within its scope.** Don't re-validate what an upstream
  layer has already asserted. Catch only what you can honestly diagnose.

## Execution Guidelines

- Comments and docstrings point inward, not outward: Don't cite or ref external
  documents that might go stale. Exception: Load-bearing code-to-code references
  and cross-file contracts.
- When writing markdown, add `<!-- prettier-ignore -->` in front of tables to
  avoid wrapping at 80 chars.
- Use `uv`, never `pip`.
- Use `uv run ...`, never `python3` or `python`.
- Don't add dependencies; ask first if there is need. Everything in
  `pyproject.toml` is approved.
- See `.env.example` for available env vars.
- Starting Dagster starts the production automation — all three
  schedules/sensors default to RUNNING. `dagster dev` is not a harmless graph
  viewer.
- The dbt default target is `dev`. Never point a build at `prod` without asking.

## Docs

This is the only file that routes between documents. Everything else is
self-contained.

Read for any session:

- `OVERVIEW.md` — architecture, data flow, boundaries, contracts. Captures the
  project's current state, frequently derived from source. Carries its commit as
  ref.

Read only when needed:

- `DECISIONS.md` — rationale, rejected alternatives, and the measurements frozen
  at decision time. Not derivable from code. Append when a load-bearing design
  decision is made; amend only when one is reversed.

- `FINDINGS.md` — current analytical results, reconciliation baselines, and
  drift anchors, stamped with the bounds they were computed under. Read before
  interpreting any gold output or judging whether a run has regressed. Rewrite
  after a prod run that changes results.

Read only when explicitly prompted to:

- `docs/design-archive/` — implemented design contracts and superseded designs,
  kept for archaeology.
- `docs/openalex/` — official OpenAlex docs.

Do not read as an authority:

- `README.md` — human-facing. It duplicates content freely, at lower
  granularity, and is authoritative for nothing. Where it disagrees with
  `FINDINGS.md` or `DECISIONS.md`, they win.

Never search the web for documentation, unless explicitly asked to.
