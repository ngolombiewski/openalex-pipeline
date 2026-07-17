# PLAN.md — Orchestration review fixes (STATE step 9, review round 2)

_Scope: resolve the findings from `REVIEW.md` (2026-07-17) plus one additional finding from the first-pass review, so the orchestration stage can be committed. This plan itself went through a review round (2026-07-17); the revisions from that feedback are folded in below — notably F1 (bounded retries instead of unlimited), F2 (request/executor split + tombstone durability), and F3 (explicit manifest preparation; `prepare_if_dev()` alone is a no-op outside `dagster dev`). The previous PLAN (dbt steps 4–8) is complete and retired; see STATE.md. After this: step 10, the Streamlit dashboard (needs its own design pass; the gold Q2/Q3 revisit — cohort coverage, Gini through current year, pooled AI-vs-rest variant tables per `docs/gold-design.md` §9 — slots in before or alongside it, Nils decides)._

**For the implementation agent — ground rules:**

- Read `docs/orchestration-design.md` and `REVIEW.md` in full first. The design doc is the contract; nearly every fix below changes it (F0 §7, F1 §4c/§5, F2 §6, F3 §7, F4 §7, F5 §5, F6 §5, F7 §7, F8 §3) — update the affected sections in the same change so doc and code never diverge.
- Contracts → tests → implementation, per AGENTS.md. REVIEW finding 7 exists because the first pass skipped behavioral tests; write the failing test before the fix wherever feasible.
- `uv run ...` for everything. No new dependencies. Do not commit — Nils commits after review.
- Existing suite is 174 green; it must stay green. New pyright/ruff issues in touched files: none (repo-wide pre-existing debt is out of scope).

---

## F0 — Instance config: ship a canonical `dagster.yaml` (prerequisite for F1)

F1 needs automatic run retries. That setting lives at `$DAGSTER_HOME/dagster.yaml`, but `DAGSTER_HOME` is the disposable, gitignored `.dagster/` state directory (F4). Correctness must not depend on configuration that disappears when advisory state is cleared.

**Fix:** track the canonical config as `dagster.yaml` at the repository root. `.envrc` creates `$DAGSTER_HOME` and an idempotent symlink `.dagster/dagster.yaml -> ../dagster.yaml` on every direnv load. Keep `.dagster/` wholly gitignored. The config contains `run_retries: enabled: true` for F1; local-filesystem serialization is enforced in code by F2, not by disposable Dagster instance configuration.

After intentionally wiping `.dagster/`, `direnv reload` (or re-entering the directory) is part of restart: it recreates the directory and config link before Dagster starts. The tracked root config survives the wipe, so clearing Dagster history still cannot remove a correctness guard.

**Test:** load a temporary `DagsterInstance` from the tracked config and assert automatic run retries are enabled. Manual verification in F4 confirms the symlinked config is the one loaded from the real `DAGSTER_HOME`. Document the config/state separation in design doc §7.

## F1 — Sensor retry policy: neither zero nor unlimited (REVIEW #1, High; revised)

`warehouse_staleness_sensor` returns `RunRequest(run_key=f"warehouse_build:{latest_upload.isoformat()}")`. Dagster launches at most one run per sensor run key **ever** — including failed runs — so after one failed `warehouse_build` the sensor never retries until a new upload changes the key: the self-healing property is silently dead. But the first-draft fix (drop the `run_key`) overshoots into the opposite failure: a _deterministic_ dbt failure (and dbt runs tests interleaved between models, so a staging test failure permanently strands silver/gold as stale) would re-trigger a ~43 GiB build every 4 hours indefinitely — that alone blows the BigQuery free tier inside a week.

**Fix — one stable request per upload, finitely retried:**

- **Keep** the `run_key` (`warehouse_build:{max(uploaded_at).isoformat()}`) — exactly one _launch_ per converged upload state;
- add the run tag `"dagster/max_retries": "3"` to the `RunRequest`, with `run_retries` enabled in `dagster.yaml` (F0) — the daemon may immediately re-execute a failed run up to 3 times: **four total attempts** including the initial run, bounded but not delayed across later sensor ticks;
- after retries exhaust: the warehouse stays stale and the sensor stays silent for that key — bounded, and loud via the visible failed runs; the next refresh (new upload timestamp → new key) gets fresh attempts.
- Keep the in-progress guard and `minimum_interval_seconds`.

Compatibility with the advisory-log principle: retry counting lives in Dagster history, but wiping `DAGSTER_HOME` can only permit extra _attempts_ — the key is forgotten, so a fresh initial launch plus its retry budget, up to four additional attempts — it can never mark stale data fresh. Correctness still derives solely from FS/GCS/BQ. State this in design doc §4c.

**Tests (first):** sensor-level tests using `build_sensor_context` with mocked instance and mocked `cloud`/predicate seams:

- converged ∧ stale → `RunRequest` with the upload-derived `run_key` **and** the `dagster/max_retries` tag;
- same upload timestamp across evaluations → same key (dedupe is the daemon's job; we pin key stability); newer upload timestamp → different key;
- not converged → `SkipReason`; converged ∧ fresh → `SkipReason`; run in progress → `SkipReason` (mock `instance.get_runs`); shared lock unavailable → `SkipReason("local pipeline mutation in progress")` (mock the lock seam; the real-lock test lives in F2).

These double as the missing sensor-path coverage from REVIEW #7.

## F2 — Invalidation: interruption-safe **and** concurrency-safe (REVIEW #2, High; revised)

`invalidate_year` deletes the extraction dir, then the bronze parquet. An interruption between the two leaves old parquet beside a re-extracted year; bronze classifies the year as already ingested and convergence accepts stale data (reproduced in review). Reversing the order alone still allows a silently skipped refresh. Additionally, a resume-check only at the start of `extracted_jsonl` cannot stop an invalidation that starts _after_ that check — the two jobs can overlap (manual runs, delayed ticks, separate processes), and deletion racing a mid-sweep bronze ingest is exactly the stale-parquet corruption again.

**Fix — request/executor split.** Deletion happens in exactly one place, inside the sweep, strictly ordered before extraction:

- The monthly job becomes a pure **request**: guard (`classify_year` COMPLETE with the canonical query; absent/in-progress → no-op skip; `CorruptedState`/`QueryMismatch` propagate), then atomically create the tombstone `{extract_root}/_INVALIDATING_{year}` and stop. **It deletes nothing.** A near-instant marker write cannot race a running sweep's reads destructively — worst case the marker sits until the next sweep.
- `resume_pending_invalidations(extract_root, bronze_root, expected_years)`, called at the top of the `extracted_jsonl` asset before `extraction_runner.run()`, is the sole **executor**: for every tombstone found it unconditionally deletes `{bronze_root}/{year}.parquet` (if present), then `{extract_root}/{year}/` (if present), then removes the tombstone. `expected_years` is passed explicitly from orchestration config so tombstone bounds are validated without reaching into `Settings`. No COMPLETE guard here — the guard ran at request time; whatever remains is pending work.

**Filesystem serialization:** add a small orchestration-only `local_data_lock` context manager over standard-library `fcntl.flock` on `{OPENALEX_DATA_ROOT}/.orchestration.lock`, supporting **two modes**:

- **exclusive, blocking** (`LOCK_EX`) — held by every Dagster compute that reads or writes the local chain (`extracted_jsonl`, `bronze_parquet`, `bronze_gcs`, and `invalidate_refresh_year_op`) for its complete execution;
- **shared, non-blocking** (`LOCK_SH | LOCK_NB`) — used by the sensor (below).

It creates the data root before opening the lock so bootstrap-from-scratch still works. This covers scheduled jobs, named-job manual runs, and Dagster's implicit asset-materialization jobs; correctness does not depend on run tags or Dagster history. The kernel releases the lock after process death. Direct CLI calls to the underlying modules do not acquire it and remain the explicit operational exception below.

Blocking on the exclusive lock is **intended behavior**: a monthly request op (or a second sweep) queued behind a multi-hour extraction simply waits and then runs — do not "improve" the writer path with `LOCK_NB`/timeouts, which would turn a transient collision into a refresh silently deferred by a month.

**Sensor reads take the shared, non-blocking mode.** Lock-free sensor reads have a TOCTOU race: a tombstone scan can pass, then a request lands and the sweep's executor starts deleting, and the sensor's continuing `classify_year` reads a mid-`rmtree` directory (loudly misreported as `CorruptedState`). Atomic file writes and scan ordering do not close this — only excluding writers for the duration of the read does. The sensor therefore attempts `LOCK_SH | LOCK_NB`; if unavailable (a writer holds `LOCK_EX`), it returns `SkipReason("local pipeline mutation in progress")` — never blocking evaluation behind a multi-hour sweep. If acquired, it holds the shared lock across GCS-year metadata collection **and** `is_converged` (the local-mtime-vs-blob comparison must be coherent), then releases it before the upload-manifest and BigQuery checks, which touch no local state. Shared holders don't exclude each other, only writers — and a writer arriving mid-evaluation blocks until the sensor's brief read completes, which is the point.

**Tombstone durability** — presence authorizes unconditional deletion, so it gets the same rigor as extraction's completion signals:

- create with `O_EXCL` (fail if it already exists; an existing tombstone means the request is already pending → the request op reports that and stops);
- **empty content** — presence _is_ the signal; recovery must never depend on parseable content (no JSON);
- fsync the marker file and its parent directory before returning from the request;
- after deletion, fsync `bronze_root` (only if it exists — bootstrap and extraction-only states legitimately lack it) and `extract_root` before removing the marker, then fsync `extract_root` again after marker removal — the durable tombstone cannot disappear before the deletions it authorizes are durable;
- a tombstone whose `{year}` suffix does not parse as an int in `expected_years` is corruption → new typed exception (e.g. `TombstoneCorruption` in `orchestration/exceptions.py`), raised by both the executor and convergence, propagates loudly.

**Convergence:** `is_converged` returns `False` while a valid in-scope tombstone exists (a pending-but-not-yet-executed invalidation is by definition not converged). With the shared sensor lock this check is no longer safety-critical ordering — writers are excluded for the whole evaluation — but keep the tombstone scan first as a cheap short-circuit. A malformed or out-of-scope `_INVALIDATING_*` marker raises `TombstoneCorruption`; corruption is never silently reduced to non-convergence.

**Result contracts:** replace the old deletion-shaped result with request/execution-specific immutable results. The request distinguishes `requested`, `skipped_pending` (marker already exists), `skipped_in_progress`, and `skipped_absent`; it checks for an existing marker **before** treating a missing year directory as absent. Executor results report the year and which artifacts were actually deleted, one result per valid tombstone. Pin these docstrings before writing tests.

**Residual concurrency, handled or accepted explicitly (design doc §6):**

- Overlapping Dagster runs and direct asset materializations: serialized at the compute boundary by the data lock's exclusive mode. Runs may interleave between assets, but no two local-chain computes can read/write concurrently, the executor can never delete while bronze or upload is using local files, and no writer can start while the sensor holds its shared-mode read.
- Ad-hoc CLI invocations of the underlying modules bypass Dagster entirely; that exposure predates orchestration and is accepted as an operational assumption — state it, don't hide it.
- A request landing while extraction has the target year mid-pull: guard sees IN_PROGRESS → skip → that month's refresh is deferred. Rare (bootstrap or a straddling pull); accepted and documented.

Note the discovery patterns: extraction looks only at `{year}/` dirs and bronze's `discover_years` matches all-digit parquet stems, so `_INVALIDATING_*` files in `extract_root` are invisible to both — verify with a test, don't assume.

**Tests (first):** request writes tombstone without deleting; request with existing tombstone (including a partly executed request whose year dir is absent) → `skipped_pending`; executor from each interruption point (tombstone + both artifacts → both deleted + marker removed; tombstone + parquet gone → dir deleted; tombstone alone → removed); malformed/out-of-bounds tombstone → executor and convergence raise; successful request+execute leaves no tombstone; `is_converged` false while a valid tombstone exists; executor with no tombstones is a no-op; extraction/bronze discovery ignores tombstones; wrapper tests assert every local compute enters the exclusive lock. Focused multiprocessing tests over the real lock: (a) exclusive held in one process → a second exclusive acquirer blocks until release; (b) exclusive held → sensor's `LOCK_SH | LOCK_NB` attempt fails immediately (the skip path); (c) shared held by a reader → an exclusive writer blocks until the reader releases (writer exclusion during sensor evaluation).

## F3 — dbt manifest preparation must work outside `dagster dev` (REVIEW #3, High; revised — was the plan-review blocker)

`@dbt_assets` reads `dbt/target/manifest.json` at import; `dbt/.gitignore` excludes `target/` (and `dbt_packages/` is gitignored too). A clean checkout cannot load the definitions. The first-draft fix (`DBT_PROJECT.prepare_if_dev()`) is wrong: it only acts when `DAGSTER_IS_DEV_CLI` is set, i.e. under `dagster dev` — it is a no-op for `dagster-daemon`, pytest imports, and definitions validation.

**Fix — explicit preparation on every definitions-process startup.** A small helper (e.g. `orchestration/dbt_prep.py::prepare_dbt_project()`) called at module load in `definitions.py` before the decorator touches `manifest_path`:

- if `dbt_packages/` is missing → run `dbt deps`;
- **always** run `dbt parse` (prod target, project + profiles dirs as pinned on `DbtProject`) once when the definitions module loads in a process — presence alone is insufficient because an existing manifest may be stale relative to dbt source files;
- invoke dbt programmatically (`dbtRunner`) or via subprocess — implementer's choice, but failures must propagate loudly with a message naming the missing prerequisite (the direnv env: `dbt parse` resolves `env_var('OPENALEX_GCP_PROJECT')` in `profiles.yml`);
- **serialize the preparation itself**: the supported daemon mode launches `dagster-daemon` and `dagster-webserver` as separate processes, each of which loads the definitions module — two concurrent `dbt parse` runs writing the same `dbt/target/` can produce a torn `manifest.json` (dbt does not promise atomic artifact writes). Guard the helper with `fcntl.flock(LOCK_EX)` on its own lock file (`dbt/.prepare.lock` — *not* F2's data lock; unrelated concerns must not share a mutex; add the lock file to `dbt/.gitignore`), and after acquiring, run parse and only then read the manifest — the second process re-parses harmlessly rather than reading mid-write.

This is one deterministic contract for all three launch paths (`dagster dev`, daemon, pytest). Python module caching bounds it to once per definitions process, while every process restart refreshes the manifest.

**Accepted trade, state it in the design doc:** parse-on-load means *importing* `definitions` hard-requires the direnv environment and costs ~5–15 s per process, and a parse failure fails the import loudly. That is deliberate (a stale manifest silently mis-mapping assets is worse), and it is cheap here because only the definitions smoke test and the F3 integration test import the real module — all other unit tests mock at the preparation seam or below and must stay that way. Document it in design doc §7 as the startup contract: _importing the definitions requires the direnv-active environment and prepares a current dbt manifest; there is no separate packaging step._ A package change still requires `dbt deps` explicitly or removal of `dbt_packages/`; the lockfile remains the pinned dependency contract.

**Tests (first):**

- unit: helper with mocked dbt invoker — parse is invoked whether the manifest is present or absent; deps is invoked iff `dbt_packages/` is missing; parse/deps failures propagate; preparation runs under the prepare lock (assert at the lock seam, mirroring F2's lock tests);
- integration (the real clean-checkout regression): in a **subprocess** (monkeypatching after import is too late for the decorator), copy the project `src/` and `dbt/` trees to a temporary repo, remove its `dbt/target/`, copy `dbt_packages/` in to avoid network, point `PYTHONPATH` at the temporary `src`, and import the copied definitions module → import succeeds and a prod-target manifest exists afterwards. Do not move or delete the working tree's target artifact.

## F4 — `DAGSTER_HOME` bootstrap (REVIEW #4, High)

`.env.example` sets `DAGSTER_HOME=.dagster`; Dagster requires an absolute path to an existing directory, so the documented value breaks the daemon.

**Fix:** bootstrap via `.envrc` (direnv is already the env mechanism): export the absolute `DAGSTER_HOME="$PWD/.dagster"`, create it, and idempotently refresh its `dagster.yaml` symlink to the tracked repository-root `dagster.yaml` from F0. Update `.env.example` to state that `DAGSTER_HOME` is exported and initialized by `.envrc`, not set to a relative value. Keep `.dagster/` wholly gitignored. Document that editing `.envrc` requires `direnv allow`, and clearing `.dagster/` requires `direnv reload` before restarting Dagster.

**Test:** none automatable worth having (direnv is outside pytest); covered by the manual verification below.

## F5 — Upload-manifest validation: schema **and** completeness, with exception honesty (REVIEW #5, Medium; revised)

`upload_manifest_uploaded_at` returns `[]` for an absent manifest or missing `uploaded_at` column; `warehouse_is_stale` maps `[]` to `False` (fresh). Silent and wrong — the sensor reads the manifest only _after_ convergence, and a converged pipeline has run upload at least once. And schema-shape alone is not enough: a well-typed manifest can still omit the refreshed year, duplicate a year, carry null timestamps, or be empty.

**Fix:** the function takes the expected years (`upload_manifest_uploaded_at(bucket, expected_years)`) and raises a typed `UploadManifestInvalid` (in `orchestration/exceptions.py`, alongside F2's exception) when:

- the manifest object is absent;
- the parquet is unreadable or the schema differs from the pinned `UPLOAD_MANIFEST_SCHEMA`;
- the year set is not _exactly_ `expected_years` (missing, extra, or duplicated years);
- any `uploaded_at` is null; or the manifest is empty.

**Exception honesty:** only diagnosable states get relabeled — GCS `NotFound` on the object, parquet parse failures, and the validation rules above. Authentication, network, and unexpected SDK failures propagate untouched (catch narrowly; no blanket `except Exception → UploadManifestInvalid`). Remove the now-unreachable empty-list branch from `warehouse_is_stale`; the sensor lets the exception propagate — a loud evaluation error in the UI. Update design doc §5.

**Tests (first):** absent object → raises; wrong schema → raises; missing/extra/duplicate year → raises; null `uploaded_at` → raises; well-formed → values returned; a non-NotFound client error propagates as itself. Replace `test_warehouse_not_stale_without_upload_manifest_rows` with the new contract.

## F6 — Staleness: existence for all relations, timestamps for tables (first-pass finding, Medium; revised)

`dbt_model_table_names` returns **all** model nodes, including `int_paper_half_life` (`materialized='view'`). Views are not data-bearing — they read the current underlying tables at query time — so their timestamps do not belong in a data-freshness `min` (BigQuery's `modified` semantics for `CREATE OR REPLACE VIEW` are beside the point and unverified; don't lean on them). But filtering views out _entirely_ is also wrong: a missing terminal view would then never count as incomplete.

**Fix — two-tier contract with explicit relation metadata:**

- **Existence** is required for every dbt model relation materialized as a table or view: any expected relation absent from the dataset → stale;
- **freshness timestamps** are compared only over `materialized == 'table'` models: `stale iff max(uploaded_at) > min(last_modified over table-materialized models)`.

The manifest reader returns immutable relation specs (`name`, `materialization`). This pipeline pins supported physical materializations to `table` and `view`; an unexpected model materialization raises loudly rather than being guessed. The BigQuery helper returns explicit relation metadata (`exists: bool`, `modified: datetime | None`) instead of overloading `None` to mean both missing and timestamp-less. A present view may have no useful modification timestamp and is still complete. A present table without `modified` cannot establish freshness and raises a typed warehouse-metadata exception rather than triggering an endless rebuild. Update design doc §5 with this contract and rationale.

**Tests (first):** manifest fixture with a table model, a view model, a non-model node, and an unsupported materialization → table/view specs surface correctly and unsupported physical materialization raises; predicate: missing view → stale; present view with `modified=None` or an old timestamp does **not** drag the min; missing table → stale; present table with `modified=None` raises; all relations present and tables fresh → fresh.

## F7 — Activation policy (REVIEW #6, Medium — decision pinned)

Schedules and sensor currently default to `STOPPED`, while README/design describe the refresh as automated.

**Decision:** all three — `local_sweep_schedule`, `invalidate_refresh_year_schedule`, `warehouse_staleness_sensor` — get `default_status=RUNNING`. Rationale: the safety lives in the guards (idempotent sweeps, completeness-guarded invalidation requests, convergence-gated builds), not in being off; a default-STOPPED "automated" pipeline is a demo that doesn't run. The corollary must be documented just as plainly (README + design doc §7): **starting Dagster _is_ starting the production automation** — `dagster dev` against this project is not a harmless UI inspection; automation is live whenever a daemon runs from a direnv-active shell, and inert otherwise.

**Test:** assert the three definitions carry `RUNNING` default status (cheap, and pins the decision against accidental regression).

## F8 — Asset metadata overstates work performed (REVIEW #8, Low; revised naming)

A no-op sweep reports the full corpus as fetched (extraction sums persisted `records_fetched` over skipped years); upload `bytes` includes skipped objects.

**Fix — relabel as state totals, add per-run splits where the runner return types already allow (explicit over inferred; do _not_ extend runner contracts):**

- extraction: split year counts by `YearOutcome.status` (e.g. `years_completed` vs `years_skipped`); name the record sum `completed_shard_records_total` — it is the lifetime total of the completed shards visible this run, not a per-run delta (on a daily-limit stop the incomplete year is absent from outcomes, and a resumed completion reports the shard's lifetime count). The docstring/metadata description must say exactly that;
- upload: `bytes_uploaded` = sum over `result.uploaded` only; keep `uploaded`/`skipped` counts;
- bronze: already reports statuses; rename `manifest_rows` if ambiguous.

Update design doc §3's metadata column to match. **Tests:** the wrapper tests (F9) assert the split — a skip-heavy sweep reports zero per-run uploads and the state totals labeled as such.

## F9 — Missing wrapper tests (REVIEW #7, remainder)

Beyond the sensor (F1), clean-checkout (F3), and predicate tests (F2/F5/F6): one test per asset wrapper — mock the runner at the same seam the module tests use, assert it is called with config-derived arguments and that the `MaterializeResult` metadata matches F8's contract. The `extracted_jsonl` wrapper test also asserts the F2 executor runs before the extraction runner.

## Optional cleanup (take if cheap, skip if not)

- `cloud.gcs_updated_by_year`: replace per-year `exists()` + `reload()` (~154 API calls/tick) with one `list_blobs(prefix="bronze/")` pass.
- Drop the redundant `-t prod` in `dbt.cli(["build", "-t", "prod"])` — the resource already pins the target (keep exactly one explicit pin).

## Verification (before handing back)

1. `uv run pytest` — full suite green, new tests included.
2. `uv run ruff check .` and `ruff format --check` + `pyright` on touched paths — clean.
3. Clean-checkout simulation: the F3 temporary-repo subprocess test passes. In a fresh direnv shell, `uv run dagster definitions validate` succeeds; `DAGSTER_HOME` resolves absolute and exists; `.dagster/dagster.yaml` resolves to the tracked root config; a temporary-instance test proves retries are enabled.
4. Manual smoke is explicitly a production action. First evaluate the real convergence/staleness path without launching a run and record whether it returns `SkipReason` or `RunRequest`. Then run `uv run dagster dev`, confirm the asset graph renders end-to-end and the three automations show RUNNING. If the preflight was stale, expect and accept the real warehouse build rather than claiming the sensor will skip. Confirm the shared filesystem lock path is visible and no local computes overlap.
5. Update `docs/orchestration-design.md` (§3 metadata, §4c bounded/immediate retry policy, §5 predicates + manifest/relation validation, §6 request/executor tombstone protocol + filesystem lock + direct-CLI exception, §7 startup contract: activation, `DAGSTER_HOME` bootstrap, canonical `dagster.yaml`, manifest preparation, supported launch modes) and STATE.md.

**Done when:** all findings F0–F9 closed with tests, REVIEW.md's gate (findings 1–5 + activation decision) and the plan-review blocker (F3) satisfied, verification steps pass, and the docs match the implemented behavior.
