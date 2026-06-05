# PLAN.md

Open questions and parked design decisions. Each entry is something that has
been *considered* but deliberately deferred — not an inbox.

**Discipline:** when a question is resolved, the resolution moves into
`ARCHITECTURE.md` (or the relevant design doc) and the entry is removed from
this file. Ghosts accumulate otherwise.

---

## Data / Analysis

- **OpenAlex subfield IDs for AI.** The classification rule in `DATA_MODEL.md`
  uses display names (`Artificial Intelligence`, `Computer Vision and Pattern
  Recognition`). The exact numeric subfield IDs need to be pinned via the API
  before dbt staging can filter on them reliably.
- **CV/PR inclusion in the AI classifier.** Judgment call; deferred to
  analysis time. Both ablation variants (`ai_strict`, `ai_broad`) will be
  computed and differences reported, so this resolves itself empirically.
- **Citation half-life methodology.** Cohort-based approximation over
  `counts_by_year` is the intended approach. The exact assumptions —
  cohort window, the definition of "half-life" in a citation-counting
  context — need to be documented before implementing the gold model.

## Infrastructure

- **External vs. native BigQuery tables.** Start with external tables over
  GCS parquet; switch to native if query performance or cost demand it.
  Decision deferred to wiring the warehouse load.
- **`dagster-dbt` integration mode.** Native integration vs. shelling out to
  dbt. Decide when wiring Dagster orchestration.
- **GCS `_SUCCESS` marker for bronze upload.** Locally, parquet presence is
  the completion signal (Invariant 2 in bronze design). Whether GCS object
  semantics need an additional `_SUCCESS` marker — for upload races,
  eventual consistency, or partial multi-object uploads — is unresolved.
  Extraction faced and rejected the analogous question for local disk;
  revisit specifically for GCS when the upload step is built.

## Pipeline Boundaries

- **Deferred profiling pass.** Extraction deferred a full null-rate /
  filter-conformance scan over all records. Bronze is scoped as pure
  conversion and does not own it. Its home — a standalone profiling step
  or dbt staging tests — is undecided. Must be assigned before silver.
- **Raw JSONL archival.** Settled that raw JSONL stays local and does not
  upload to GCS (it is a one-time intermediate). Open sub-question: do we
  want per-year tarball archives for reproducibility insurance, or rely on
  "extraction is re-runnable from OpenAlex" as the recovery story? No
  decision yet.
- **Bronze → GCS upload: where it lives.** The upload step's contract
  ("write parquet to a root path") is orthogonal to bronze itself. Whether
  it lives as a standalone script, a step in the bronze package, or a
  Dagster asset is open. Lean: separate stage, eventually a Dagster asset.