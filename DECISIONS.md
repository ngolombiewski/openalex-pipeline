# DECISIONS.md

Why the pipeline is built the way it is. This file holds **rationale and frozen
evidence** — the reasoning behind choices, and the measurements taken once to
justify them. It is not derivable from source.

Scope boundaries:

- **What and how** the system does things → `OVERVIEW.md` (regenerated from
  source).
- **Current analytical results** and drift baselines → `FINDINGS.md`.
- **Here**: why a choice was made, what was rejected, and what was measured at
  decision time. Measurements here are frozen: they justified a choice and are
  not refreshed.

Organized topically. Dates mark when evidence was measured, not when text was
written.

---

## 1. Project posture

**This is a learning vehicle as much as an analysis.** The pipeline and its
infrastructure matter as much as the analytical output. That justifies
infrastructure the corpus size alone would not.

**Simplicity and specificity over generality.** This is a pipeline-specific
project, not a toolkit. Specific code beats abstraction; configurability that
isn't currently used doesn't get built.

**The filesystem (and cloud object/table state) is the source of truth.** Every
layer's completion signal is a file whose presence means "done," written
atomically. There is no separate state store, and no component may depend on
another component's bookkeeping. This principle is why manifests are derived
rather than authoritative, and why Dagster's event log is advisory.

**Corruption is loud.** Known failure modes get typed exceptions; unknown
failures propagate untouched. No silent recovery, no swallowed errors, no
inferred repair of a state we cannot explain.

**Trust the layer below within its scope.** A layer does not re-validate what an
upstream layer already asserted, and catches only what it can honestly diagnose.
This is what keeps the layer boundaries thin.

---

## 2. Corpus and data source

**One landing zone = one query.** An extraction root and its bronze root hold
year shards of a single filter/select. Bronze asserts query homogeneity across
all completed shards before ingesting anything and fails loudly on a mix. A
different filter/select is a different corpus and runs as a separate pipeline
instance with its own roots and bucket prefix.

Consequence: provenance lives at **year granularity**, not per record. There are
no `_extracted_at`-style columns anywhere in bronze; all provenance is in the
year-grained manifest. Rejected because per-record provenance would cost storage
on 14.8 M rows to answer a question the landing-zone rule already answers.

**The corpus is OpenAlex `works` filtered to `primary_topic.field.id:17`
(Computer Science), 1950–2026.** The end year advances by explicit annual
configuration change, never automatically.

---

## 3. AI classification

**Match on the subfield id, not the display name.** The id is the stable
upstream key; the name is a presentation string that upstream may change. Ids
are pinned as `dbt_project.yml` vars and used in silver and gold.

**Classify from `primary_topic` only, not the full `topics` array.** Simpler,
avoids double-counting, and more defensible analytically — a work's primary
topic reflects its core contribution. The full `topics` array is retained in
bronze and silver but is not used for classification.

**Whether CV/PR counts as "AI" is a judgment call, and the project refuses to
settle it.** Instead it preserves both representations and lets each question
use the more informative one:

| Construct                  | Definition                   | Used by |
| -------------------------- | ---------------------------- | ------- |
| `ai_strict`                | subfield 1702                | Q1      |
| `ai_broad`                 | subfields 1702 + 1707        | Q1      |
| `ai` / `cv_pr` / `rest_cs` | mutually exclusive partition | Q2, Q3  |

Q1 publishes both ablation variants because publication counts and shares are
additive. Q2 and Q3 use the exclusive partition instead because their measures
are **nonlinear** — a combined AI+CV/PR median or Gini would hide CV/PR's own
distribution rather than average it.

**NULL subfields are non-AI, not NULL.** The flags are kept strictly boolean via
`coalesce`, so a null-subfield work stays in the CS denominator rather than
vanishing from it. Currently defensive only — prod silver contains no
null-subfield work — but the Q3 subfield model still maps them to an explicit
`__unclassified__` bucket so the denominator reconciles rather than silently
shrinking. `__unclassified__` is not a real CS subfield and is excluded from
analytical subfield comparisons.

---

## 4. Extraction protocol

**Shard unit is one calendar year**, paginated independently with `cursor=*`.
Runs are sequential: the OpenAlex daily credit budget (~2 M records) is the
bottleneck, not wall time, and the largest year (~1.5 M) fits inside one day's
budget — so a year started fresh always completes in one run. Per-year sharding
leaves process parallelism as an option.

**The cursor is written before any page file and always holds the cursor for the
_next_ page to write.** `write_page` always overwrites `page-{next_page}`. This
makes the job **idempotent by construction**: a crash between writing a page and
updating the cursor costs exactly one re-fetched page on resume. No staleness
check, no special-casing, no reconciliation pass. This is the core idea of the
resume algorithm and should not be traded away.

**`_YEAR_REPORT.json` is the completion signal.** No separate `_SUCCESS` marker
— a second marker would be a second ledger that can disagree with the first.

**An empty page is still written, as a zero-byte file.** `write_page` does not
branch on `len(records)`. This keeps the invariant "≥1 page file exists for any
non-fresh year" true, which `classify_year` depends on to classify a crashed
zero-result year. The empty file is load-bearing, not an artifact.

**Fresh-path ordering is fixed: `fetch_page` → `initialize_year` →
`write_page`.** A first-fetch failure must leave nothing on disk.

**HTTP 429 (daily limit) is a clean stop, not an error.** It is deliberately a
plain `ConnectorError` and _not_ a `HardFailure`, so the runner can catch it as
a normal stop path and return a partial run report. Exit code 0.

**The API key is never part of query identity.** It is passed separately, never
written to disk, never logged. Query identity must survive a key rotation.

---

## 5. Bronze representation

**The eight nested fields land as raw JSON strings, verbatim — not native
Parquet structs.** The rejected alternative was inferring structs and
`json_encode`-ing them back. That loses fidelity: struct round-trip fabricates
explicit `null`s for keys a record never had. Forced-String preserves exactly
what OpenAlex emitted. Parsing happens once, in dbt staging.

**The 21-column schema is imposed on read; no inference.** Scalar dtypes are
load-bearing for integrity — a value that doesn't conform raises a Polars
`ComputeError` on read, so scalar type-conformance is a read-time invariant
rather than a separate check.

**`publication_date` and `updated_date` stay strings in bronze.** Date typing is
deferred to staging, where a malformed value can degrade to NULL under `SAFE.*`
and be counted by a test, rather than failing an ingest.

**Deduplication is deferred from bronze to staging.** At least one duplicate id
exists (most likely a stale cursor re-emitting a page). Bronze counts duplicates
and reports them; staging resolves them, because resolution needs the parsed
`updated_date` to pick the freshest snapshot.

**Manifests are derived, never authoritative.** Both the bronze and upload
manifests are rebuilt wholesale from on-disk/live state every run. Bronze's
manifest deliberately re-derives each year's status from the filesystem rather
than reusing `core.classify_year`, keeping ingestion and derived state as
siblings that only the runner joins.

---

## 6. Upload and cloud layout

**Skip iff the object exists and `blob.updated >= local mtime`.** Server-side
timestamps are the comparison basis, so the decision survives a lost local
cache. The same predicate is reused by the orchestration convergence check — one
definition of "already uploaded," not two.

**The upload manifest lives at `upload/_MANIFEST.parquet`, outside
`bronze/publication_year=*/`.** Deliberately a sibling of the Hive tree so
BigQuery's glob can never mistake it for a partition.

**Bronze files are not Hive-partitioned on local disk.** The Hive-style prefix
is added at upload time for BigQuery partition pruning; the file itself is
unchanged.

**The GCS `Bucket` is injected, never constructed in core logic.** One cloud
seam, mockable in tests, no network in the suite.

---

## 7. Warehouse modeling

**Staging does exactly four things**: parse the eight JSON columns, type the two
date columns, apply corpus-hygiene filters, dedup on `id`. No classification, no
aggregation. Silver classifies and projects but does not filter or aggregate.
Gold aggregates. Each layer trusts the one below.

**`is_retracted = false` deliberately excludes NULLs.** `NULL = false` yields
NULL, which drops the row. Measured 2026-07 at full corpus: **1,282 works
(~0.009%)** have unrecorded retraction status. We drop them conservatively
rather than infer "not retracted." `is_paratext` has no NULLs.

**Dedup keeps the freshest snapshot**
(`row_number() over (partition by id order by updated_date desc nulls last)`).
`nulls last` guards the edge where a malformed `updated_date` parsed to NULL — a
real timestamp always beats a null one. Exact ties are byte-identical re-emits,
so an arbitrary pick is fine.

**Everything materializes as a table, nothing as a view.** Staging is
parse-once; silver is a static rebuildable corpus; gold outputs are tiny. Gold
gets no partitioning or clustering — the outputs are too small to benefit.

**The dbt default target is `dev`,** so a bare `dbt run` can never touch prod.

**The bronze schema is pinned in the external table, not autodetected.**
`publication_year` comes from the Hive partition key and must **not** appear in
the declared schema — BigQuery rejects creation when a field is in both. The API
nevertheless _returns_ the schema with the partition column appended, so without
`lifecycle { ignore_changes = [schema] }` Terraform would see a permanent diff
and force-replace the table on every plan.

Consequence, and it is a trap: editing the schema list produces **no plan diff**
on an existing table. Creation and replacement do apply it. A deliberate schema
change requires
`terraform apply -replace=google_bigquery_table.bronze_external`. The block also
masks genuine console-side drift. Accepted because an external table is a
pointer and recreating it is free.

---

## 8. Analytical questions

### Q1 — AI's share of CS works

**No cohort restriction.** A within-year ratio is immune to the citation-window
and age confounds that force cohort control on Q2 and Q3. Denominator is every
silver work in the year.

**Published long over the two variants**, so a dashboard toggle is a filter
rather than a pivot.

### Q2 — Citation-weighted age of cited works

**The unit of observation is a citation event received by a CS work, classified
by the cited work.** A work receiving 100 citations in year `y` contributes 100
observations at its citation age.

This answers: _among citations received by CS works in year `y`, was attention
to AI, CV/PR, or the rest of CS concentrated on younger or older works?_

It does **not** answer: _do AI-authored papers cite newer literature?_ That
citing-side question needs reference lists; extraction retains only
`referenced_works_count`, not referenced work ids. Out of scope, and
presentation must not imply otherwise.

**Quantiles are discrete integer years.** `counts_by_year` is annual and
supports no within-year interpolation. The qth quantile is the smallest age
whose cumulative citation-event weight reaches q of the group/year total.

**Q2 replaced a per-paper half-life measure** (`int_paper_half_life`,
`gold_citation_half_life_by_subfield`). Those relations were removed from both
datasets rather than retained as secondary outputs.

**Q2 is a full-corpus snapshot, by decision.** Citation histories live on cited
works across every publication shard, so current-year-only automation cannot
extend it honestly. Advancing `citation_age_year_max` requires a manual
full-corpus refresh and prod reconciliation.

### Q3 — Citation concentration (Gini/top-k)

**A fixed citation window replaced cumulative `cited_by_count`.**
`cited_by_count` is cumulative to the snapshot date, so it is a function of a
paper's age — comparing cohorts on it measures elapsed time, not impact. The
previous design controlled for this by freezing a single 2012–2016 cohort, which
bought comparability at the price of having no time axis at all. A fixed
post-publication window gives every paper equal exposure and permits the
publication-year axis.

**The window is ages 1..N, excluding the publication year.** Age 0 is a partial
year whose length is set by publication month — a January paper gets ~12 months,
a December paper ~none. Including it yields a variable-length window (~3–4 years
for a nominal 3-year window) driven by publication date rather than impact.

Frozen evidence (2026-07): including age 0 moves subfield Gini by a mean of
−0.0055 at window 3 and −0.0042 at window 5 (range −0.0107 to −0.0015); top-k
shares move by at most 0.017; AI holds rank 3–5 of 11 in every cohort under both
variants with only two one-position swaps across 20 cases; the pooled AI-vs-rest
comparison shows zero sign reversals. The exclusion is substantively neutral —
but it was measured, not assumed, and the diagnostics remain published.

Note: ages 1..N is _not_ the paper's first N years of life. The window starts
0–12 months after publication depending on month, so papers get equal-duration
windows at different lifecycle offsets. That is the most precise comparison an
annual source supports. Sub-year windowing is not an alternative.

**Zero-citation papers are included in the headline Gini.** The uncited majority
against the cited few _is_ the concentration story; dropping zeros would
understate it. `gini_cited_only` publishes the other view separately, and the
exact decomposition `G = p + (1−p)·G_cond` relates them.

**Top-k shares are published alongside** because they are not determined by that
identity. They take `ceil(k · n_papers)` from the full cohort and allocate tied
boundary frequencies without arbitrary paper ordering, so the result is
independent of row order.

**The subfield grain is primary; the pooled grain is secondary.** AI's position
among real CS subfields is the like-for-like comparison. `rest_cs` pools
heterogeneous subfields and therefore carries between-subfield inequality that
an individual subfield does not — the pooled relation is a different question,
not a substitute. It is computed directly over papers because **Ginis do not
aggregate**.

**The 2012 cohort floor is forced by the source.** `counts_by_year` is a rolling
window; pre-2012 cohorts would silently fabricate zero-citation papers.

**Durability risk, named and unsolved:** because `counts_by_year` rolls, a
future full-corpus re-extraction may drop citation years 2012–13 and make the
earliest cohorts unrebuildable. No mitigation is in place.

**The terminal cohort carries a settling caveat.** Cells whose window ends in
the latest configured citation year rest on the least-settled year in the
snapshot. Measured 2026-07: the discontinuity is indistinguishable from ordinary
cohort variation, and its direction contradicts under-indexing (terminal cohorts
show _higher_ citations per paper and _lower_ zero shares). One snapshot cannot
separate settling from genuine cohort change, so `gini_citation_year_max` stayed
at 2025 and the caveat is a presentation requirement rather than a data
restriction.

---

## 9. Orchestration

**The pipeline does not strictly need an orchestrator.** The corpus is static,
every layer is an idempotent sweep, and a human running three commands is a
working schedule. Dagster is here for two reasons, in this order: (1)
demonstration — an orchestrated end-to-end asset graph is itself a deliverable;
(2) one real operational need — the current year is unstable and should be
re-pulled on a cadence, with the warehouse rebuilt when new data lands.
Everything Dagster does maps to one of those two. No ceremony.

**Dagster's event log is advisory.** A materialization record is a log entry,
never a precondition. Wiping `DAGSTER_HOME` loses history, never correctness.
Every trigger predicate derives from filesystem, GCS, or BigQuery metadata —
never from Dagster's own records.

**The runners stay authoritative.** Assets are thin wrappers around existing
`run()` entry points. Skip/resume logic lives in the modules; Dagster never
re-implements or second-guesses it.

**Sweep over cascade.** Because every runner is a whole-corpus idempotent sweep
with filesystem completion signals, "run the chain daily" _is_ the per-year
event cascade. Bootstrap-from-scratch and steady-state refresh are the same job
at different points of convergence. Partitioned assets were rejected
(2026-07-08): they would create a second completion ledger that can drift from
the manifests.

**Convergence predicates take cloud metadata as arguments.** They import no
Dagster APIs and write no state, so they stay unit-testable without cloud
access.

**Local access is serialized with a filesystem lock.** Writers take `LOCK_EX`
and block; the sensor takes `LOCK_SH | LOCK_NB` and skips rather than waits — a
sensor that blocks on a long sweep is a stuck sensor.

**Invalidation is a durable request/execute protocol,** not a direct delete. The
monthly job writes a tombstone; the next extraction executes it in
interruption-safe order. A crash between request and execution leaves a
recoverable state rather than a half-deleted year.

**Definitions startup always parses a fresh prod-target dbt manifest,** under a
dedicated `dbt/.prepare.lock` so daemon and webserver processes cannot write a
torn `manifest.json`. Consequence: importing `orchestration.definitions`
hard-requires the direnv-active environment and costs one dbt parse. Failure
aborts the import loudly. Accepted — a stale manifest is a worse failure than a
slow import.

**All three automations default to RUNNING.** Starting Dagster is starting the
production automation; `dagster dev` is not a harmless graph viewer.

**The daemon runs on a laptop,** so schedules are inert while it is down. At
daily/monthly cadence with idempotent sweeps and state-derived predicates,
missed ticks are harmless: the next evaluation converges to the same result.

---

## 10. Cost and storage

**Physical (compressed) storage billing on both analytics datasets.** Measured
2026-07: `stg_works` compresses ~11.5× (22.9 GiB logical → 2.0 GiB physical),
which keeps the datasets inside the 10 GiB free tier despite physical billing's
2× per-GiB rate. Trade-off accepted: physical also bills time-travel and
fail-safe bytes, and dbt's `CREATE OR REPLACE` leaves an old version behind on
every rebuild — so time travel is capped at the 48 h minimum to bound rebuild
churn. Fail-safe is a fixed, non-configurable 7 days. Note the billing model can
only change once per 14 days per dataset.

**`maximum_bytes_billed = 100 GiB` per job, on both targets.** A per-job circuit
breaker, not a cumulative budget. Sized to clear the full `stg_works` external
scan (~45 GiB uncompressed) with margin while killing a runaway. Harmless on
dev's decade slice.

**The raw dataset has `delete_contents_on_destroy = false`;** the analytics
datasets have `true`. Analytics content is dbt-rebuildable from the external
table; anything unexpected in `openalex_raw` should fail a destroy rather than
be silently deleted. The bucket carries `prevent_destroy`.

---

## 11. Dev slice

**The canonical dev slice is publication years 2012–2016.** It is an exact
overlapping-cohort preview for Q3 and a cheap structural target for Q2 — but
**dev Q2 values do not preview prod**, because the slice omits older cited
works. Structurally valid, analytically unrepresentative.

**The dev slice is not bit-exact against prod, by design.** `stg_works` dedups
on work id _after_ the year filter, so a work OpenAlex re-dated across
extraction snapshots can land in a dev cohort that prod excludes. Measured
2026-07: dev holds 12 more works in 2012–2016 than prod (2,668,938 vs
2,668,926); all 12 exist in prod under a later publication year. Prod is
correct; the effect is 4.5e-6 of the slice. Q3 dev/prod reconciliation therefore
runs under tolerance, not exactly.
