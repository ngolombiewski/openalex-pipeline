# Design: Silver — AI classification + analytical flattening

*Scope: the first modeling layer. Takes `stg_works` (parsed, typed, deduped
works) and produces the classified, analysis-shaped table the gold aggregates
read. Applies the `ai_strict`/`ai_broad` ablation and projects the work grain
down to the columns Q1–Q3 need. Stops before any aggregation (that is gold) and
before the half-life/Gini methodology (deferred to the gold design).*

*Status: design — to hand to an implementing agent.*

---

## 0. What this layer is

`stg_works` is corpus-hygiene-clean but analytically raw: one row per CS work,
nested fields flattened, but no notion of "AI". Silver adds exactly two things:

1. **Classification** — the `ai_strict` / `ai_broad` ablation flags
   (`DATA_MODEL.md`), computed once here so every gold question groups by the
   same definition.
2. **Projection to the analytical grain** — carry forward only the columns the
   three questions need, dropping the low-signal staging columns (`keywords`,
   `topics`, `ids` crosswalk, percentile blocks, `open_access`). Staging keeps
   the full parse; silver is the narrowed, analysis-shaped view.

No aggregation, no reshaping of `counts_by_year` (stays nested — gold's Q2
concern), no new filters (trust staging).

```
stg_works  ──►  silver_works
 (one row per CS work)   (+ is_ai_strict, is_ai_broad; projected columns)
```

Single model, single grain: **one row per work**, same as staging. We do *not*
introduce a long citations fact here (see §6).

---

## 1. Input / output

| | |
|---|---|
| **Input** | `{{ ref('stg_works') }}` — the native staging table. |
| **Output** | `silver_works`, native table in `openalex_analytics` (prod) / `_dev`. |
| **Grain** | One row per OpenAlex work `id` (unique, inherited from staging). |
| **Materialization** | `table`, partitioned by `publication_year` (int range 1950–2026), clustered by `primary_topic_subfield_id` — identical to staging (§4). |

Silver does no filtering: `stg_works` already applied the quality filters,
corpus bounds, and dedup. Row count of `silver_works` == row count of
`stg_works` (asserted, §5). "Trust the layer below."

---

## 2. Classification — the core of this layer

### 2a. Match on the subfield **id**, not the display name

`DATA_MODEL.md` defines the AI subfields by name; OpenAlex assigns each a stable
numeric subfield id. We match on the **id** — names are presentation strings
that can be re-worded upstream, ids are the contract. Confirmed against the
corpus (prod `stg_works`):

| Subfield | id | works | share of CS |
|---|---|---|---|
| Artificial Intelligence | `https://openalex.org/subfields/1702` | 4,047,312 | 27.5% |
| Computer Vision and Pattern Recognition | `https://openalex.org/subfields/1707` | 1,844,113 | 12.5% |

So `ai_strict` ≈ 27.5% and `ai_broad` ≈ 40.0% of CS — a useful order-of-magnitude
sanity anchor for Q1, not a target.

### 2b. Pin the ids as `vars` (single source of truth)

The ablation is a reviewed analytical definition, so it lives in
`dbt_project.yml` as named scalars, commented back to `DATA_MODEL.md` — not
buried inline in SQL:

```yaml
vars:
  subfield_ai:    'https://openalex.org/subfields/1702'  # Artificial Intelligence
  subfield_cv_pr: 'https://openalex.org/subfields/1707'  # Computer Vision and Pattern Recognition
```

(A seed table mapping id→variant would be the move if the classification ever
grows beyond two subfields; for two ids that is over-engineering — YAGNI.)

### 2c. Two boolean flags, with the ablation as a subset relation

```sql
primary_topic_subfield_id = '{{ var("subfield_ai") }}'                         as is_ai_strict,
primary_topic_subfield_id in ('{{ var("subfield_ai") }}',
                              '{{ var("subfield_cv_pr") }}')                    as is_ai_broad,
```

The flags are booleans on the work row — **not** an exploded long/variant table.
Q1–Q3 then become a plain `GROUP BY` + `COUNTIF`/filter per variant. By
construction `is_ai_strict ⊆ is_ai_broad` (strict is a subset of broad); this is
asserted as a test (§5), not just assumed.

### 2d. primary_topic-less / NULL-subfield works — resolved, with a defensive default

`staging-design.md` §7 flagged this as open. The corpus resolves it: extraction
filters to `primary_topic.field.id:17`, so a work *without* a primary_topic
cannot enter bronze at all — and indeed `primary_topic_subfield_id` had **0
nulls across all 14.7 M rows** at the step-6 prod run. So in practice every work
has a subfield and lands in exactly one of {AI, CV/PR, other-CS}.

The defensive default still matters because the staging `not_null` test is
deliberately kept at `warn` (a future refresh could introduce a null):

- A NULL subfield matches neither id → **both flags `false`** (non-AI). Correct:
  we never infer AI from absence.
- It **stays in the CS denominator**. Every silver row is CS by
  `primary_topic.field.id = 17` (guaranteed upstream), so the Q1 denominator is
  simply *all of `silver_works`*. A null-subfield work is CS-but-not-AI, which
  is the honest classification.

No special-casing in the SQL is required — the equality/`IN` predicates already
yield `false` (not NULL) the way they're written, because a NULL `=`/`IN`
comparison is NULL, and we coalesce the flags to `false`:

```sql
coalesce(primary_topic_subfield_id = '{{ var("subfield_ai") }}', false) as is_ai_strict,
```

This keeps the flags strictly boolean (never NULL), which the `not_null` tests
in §5 depend on.

---

## 3. Columns `silver_works` carries

Projected from `stg_works` to the analytical set. Identity + dimensions +
the measures the three questions consume:

| Column | Source | Used by |
|---|---|---|
| `id` | staging | key |
| `publication_year` | staging | Q1 (time axis), partition |
| `publication_date` | staging | available; finer time grain if needed |
| `primary_topic_subfield_id` | staging | classification, cluster, Q1/Q2/Q3 grouping |
| `primary_topic_subfield_display_name` | staging | readable subfield label |
| `primary_topic_id` / `primary_topic_display_name` | staging | topic-grain detail (cheap to keep) |
| `is_ai_strict`, `is_ai_broad` | **derived (§2)** | every gold question |
| `cited_by_count` | staging | Q3 (Gini on citation impact) |
| `fwci` | staging | Q3 alternative impact measure |
| `counts_by_year` | staging (nested, carried as-is) | Q2 (half-life) |

Dropped (kept in staging, re-derivable if a question later needs them):
`title`, `type`, `language`, `referenced_works_count`, `is_oa`/`oa_status`,
the percentile blocks, `keywords`, `topics`, the `ids` crosswalk, `doi`. This is
the "project to needed" call; flag at review if you'd rather silver carry
everything.

`counts_by_year` stays a nested `ARRAY<STRUCT<year, cited_by_count>>` — silver
does not reshape it. The half-life reshape and methodology are gold's (§6).

---

## 4. Materialization

```sql
{{ config(
    materialized='table',
    partition_by={'field': 'publication_year', 'data_type': 'int64',
                  'range': {'start': 1950, 'end': 2027, 'interval': 1}},
    cluster_by=['primary_topic_subfield_id']
) }}
```

Same shape as staging: a static, fully-rebuildable corpus → `table`, not
incremental. Partition + cluster mirror staging so per-year and per-subfield
gold scans prune.

---

## 5. Tests (`models/silver/_silver.yml` + singular)

- `id`: `not_null`, `unique` (grain unchanged from staging).
- `is_ai_strict`, `is_ai_broad`: `not_null` (flags are strictly boolean, never
  NULL — §2d).
- **Ablation subset invariant** (`dbt_utils.expression_is_true`):
  `is_ai_broad or not is_ai_strict` — every strict-AI work is also broad-AI.
- **Classification correctness** (`dbt_utils.expression_is_true`):
  - `is_ai_strict` ⇒ subfield id = `subfield_ai`.
  - `is_ai_broad` ⇒ subfield id ∈ {`subfield_ai`, `subfield_cv_pr`}.
- **No rows added or lost vs staging** (singular test): row count of
  `silver_works` equals row count of `stg_works`. Silver is a projection +
  classification, never a filter.
- `primary_topic_subfield_id`: `relationships`/membership is not asserted (it is
  an opaque upstream id); the classification-correctness tests above are the
  meaningful guard.

Iterate on the dev decade slice (`--vars '{year_min: 1991, year_max: 2000}'`),
then prod.

---

## 6. Deferred to the gold design (flag, don't solve here)

- **`counts_by_year` reshape location + half-life methodology.** Q2 needs a long
  (work, year, citations) shape and a *definition* of half-life (what "half"
  measures — cumulative-to-50%-of-lifetime? a fixed window? — plus interpolation
  and the treatment of the ~61% of works with empty `counts_by_year`). Both are
  gold concerns. Recommendation carried forward: keep `counts_by_year` nested in
  silver; unnest in a **gold intermediate** specific to Q2, not a second silver
  grain (single consumer → YAGNI on a silver citations fact). Reviewer may
  override and put a `silver_citations_yearly` fact here instead.
- **Q3 Gini computation** (window-function formulation, unit of analysis,
  zero-citation works) — gold.
- **Q1 denominator** is settled here (all of `silver_works`); gold just groups.

---

## 7. Implementation order

1. Add the two `subfield_*` vars to `dbt_project.yml` and the `silver:`
   materialization block (mirrors `staging:`).
2. `models/silver/silver_works.sql` (§2–§4): `ref('stg_works')`, derive the two
   flags (coalesced boolean), project the §3 columns.
3. `models/silver/_silver.yml` + the singular row-count test (§5).
4. `dbt build --select silver_works` on the dev decade slice; iterate green.
5. `dbt build -t prod --select silver_works`; spot-check the strict/broad shares
   against the §2a anchor (≈27.5% / ≈40% of CS) and confirm the row count equals
   `stg_works`.

---

## 8. What "done" looks like

- `silver_works` builds on dev then prod; row count == `stg_works`
  (14,723,333).
- All §5 tests green — in particular the subset invariant and the two
  classification-correctness assertions.
- Strict/broad shares land near the §2a anchor (a wildly different number means
  the match key or the vars are wrong).
- A reviewer can read this doc and see the ablation is a pinned, tested
  definition (`vars` + correctness tests), not a magic string in SQL.
