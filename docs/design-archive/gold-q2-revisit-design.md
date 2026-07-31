# Gold Q2 revisit design — annual citation age

*Status: reviewed, approved, implemented, deployed, and prod-reconciled. This
document is the active design for Q2. It supersedes only the Q2 contract in
`docs/design-archive/gold-design.md`; Q1 and Q3 are unchanged.*

## 1. Decision

Q2, **The Shelf Life**, asks:

> How does the age of cited literature differ among Artificial Intelligence,
> Computer Vision and Pattern Recognition, and the rest of Computer Science —
> and how have those differences changed since 2012?

The headline measure is the citation-weighted median age of cited works,
reported annually for three mutually exclusive cited-work groups. It is an
aggregate cited-work age measure, not a per-paper lifecycle measure.

The previous Q2 relations are removed rather than retained as secondary
outputs:

- `int_paper_half_life`
- `gold_citation_half_life_by_subfield`

Their historical rationale remains in the archived gold design and git
history. Active documentation and presentation must not describe them as
current outputs.

## 2. Meaning and orientation

The unit of observation is a **citation event received by a CS work** in a
given year. Classification applies to the cited work.

For a cited work `p` and citation year `y`:

```text
citation_age = y - p.publication_year
weight       = p.counts_by_year[y].cited_by_count
```

A work receiving 100 citations in year `y` contributes 100 observations at
its citation age. A work receiving no citations in that year contributes
none. The metric therefore describes the age distribution of citation
attention, not the age distribution of unique cited works.

This answers:

> Among citations received by OpenAlex CS works in year `y`, was attention to
> AI, CV/PR, or the rest of CS concentrated on younger or older works?

It does **not** answer:

> Do AI-authored papers cite newer literature than non-AI papers?

That citing-side question requires reference lists and referenced-work
metadata. The current extraction retains only `referenced_works_count`, not
the referenced work ids, and is out of scope for this revision.

## 3. Population and time bounds

### 3a. Cited-work population

The population is every row in `silver_works`, hence:

- OpenAlex works whose `primary_topic.field.id` is Computer Science (`17`);
- the existing staging hygiene filters and id deduplication already applied;
- one row per cited work;
- AI classification derived from the cited work's primary-topic subfield.

Trust the silver contract. Gold does not re-validate work ids, corpus
membership, or classification correctness.

Incoming citations may originate in any field. The source does not identify
the citing works in `counts_by_year`, so Q2 neither restricts nor groups the
citing side.

The corpus begins in 1950. Citations to older CS works are outside the
extracted population. This is a left-boundary limitation, not something gold
infers or repairs.

### 3b. Citation-year window

Prod defaults are explicit dbt vars:

```yaml
citation_age_year_min: 2012
citation_age_year_max: 2025
```

The lower bound is the first year covered by the observed
`counts_by_year` histories. The upper bound is the latest complete year in the
current full-corpus snapshot. Partial 2026 data is excluded from Q2.

These vars are independent of:

- `year_min` / `year_max`, which bound publication-year rows read into
  staging;
- `partial_year`, which flags Q1's incomplete publication year;
- `OPENALEX_END_YEAR`, which controls extraction.

No rollover or automation may infer `citation_age_year_max` from one of those
settings. Advancing it is a manual analytical decision governed by the
freshness contract in §11.

Q2 publishes every citation year in the inclusive configured range. Sampling
selected years would discard trend information without reducing extraction
scope, so spaced-year samples are a presentation choice only.

## 4. Cited-work groups

Q2 partitions cited works into three mutually exclusive, exhaustive groups
using the pinned primary-topic subfield ids:

| `cited_group` | Rule |
|---|---|
| `ai` | `primary_topic_subfield_id = subfield_ai` (`1702`) |
| `cv_pr` | `primary_topic_subfield_id = subfield_cv_pr` (`1707`) |
| `rest_cs` | Every other `silver_works` row |

The `rest_cs` fallback is explicit and preserves the complete silver
denominator, including any row whose subfield id is null. This matches the
existing silver flags, which treat a null subfield as non-AI. Gold trusts that
upstream policy rather than adding another null filter.

Q2 deliberately does not publish strict/broad composites. Weighted quantiles
are nonlinear: AI, CV/PR, and rest quantiles cannot reconstruct an AI+CV/PR
quantile, while strict/broad summaries cannot reveal CV/PR's own quantiles.
The exclusive partition is preferred because it exposes the disputed category
directly and prevents a composite trend from moving merely because AI and
CV/PR citation volumes change relative to each other.

The existing `is_ai_strict` and `is_ai_broad` silver flags remain unchanged
for Q1 and other consumers. Q2 derives its three-way analytical grouping from
the same pinned ids already carried in `silver_works`.

## 5. Measures

### 5a. Citation-age distribution

For each `citation_year × cited_group`, aggregate positive citation events by
integer `citation_age`, sort ascending, and calculate cumulative citation
weight.

The three quantiles are discrete weighted quantiles:

```text
quantile(q) = smallest citation_age for which
              cumulative_citation_events >= q * citation_events
```

The model publishes `q = 0.25`, `0.50`, and `0.75` as:

- `p25_citation_age`
- `median_citation_age`
- `p75_citation_age`

All three values are integer years. Do not linearly interpolate between annual
age bins: `counts_by_year` contains no within-year timing with which to
support fractional precision.

### 5b. Volume and recency context

The model also publishes:

- `citation_events` — sum of positive citation counts in the group/year;
- `cited_works` — distinct cited works contributing at least one event;
- `share_age_lte_2` — share of citation events to works aged 0–2 years;
- `share_age_lte_5` — share of citation events to works aged 0–5 years;
- `share_age_lte_10` — share of citation events to works aged 0–10 years.

Age zero is valid. It represents a citation received in the cited work's
publication year.

No normalization for the number or age distribution of available works is
part of the metric. Q1 supplies publication-growth context; a
growth-standardized citation-age model would answer a different question and
is deferred (§13).

## 6. Gold model contract

One new table-materialized dbt model replaces both prior Q2 relations:

```text
gold_citation_age_by_year
```

Its grain is exactly:

```text
citation_year × cited_group
```

Canonical columns, in order:

| Column | BigQuery type | Contract |
|---|---|---|
| `citation_year` | `INT64` | Inclusive configured citation-year range |
| `cited_group` | `STRING` | `ai`, `cv_pr`, or `rest_cs` |
| `citation_events` | `INT64` | Positive weighted event total |
| `cited_works` | `INT64` | Positive distinct-work count |
| `p25_citation_age` | `INT64` | Discrete weighted 25th percentile, years |
| `median_citation_age` | `INT64` | Discrete weighted median, years |
| `p75_citation_age` | `INT64` | Discrete weighted 75th percentile, years |
| `share_age_lte_2` | `FLOAT64` | Citation-event share in `[0, 2]` |
| `share_age_lte_5` | `FLOAT64` | Citation-event share in `[0, 5]` |
| `share_age_lte_10` | `FLOAT64` | Citation-event share in `[0, 10]` |

The table contains three rows per configured citation year. A group with no
citation events would make its quantiles undefined and violates the current
corpus contract; it must fail tests rather than disappear silently.

No intermediate model is required. Prefer one question-shaped SQL model with
named CTEs unless implementation demonstrates a separately testable or reused
contract that justifies an intermediate.

## 7. Input handling and diagnosed anomalies

Gold unnests `silver_works.counts_by_year` and applies these rules:

1. Entries outside the configured citation-year window are out of scope.
2. Positive `cited_by_count` values contribute their full integer weight.
3. Zero counts contribute no citation events and are ignored.
4. A null citation year anywhere in an unnested source array is invalid input.
   Within the configured citation-year window, null counts, negative counts,
   and duplicate entries for the same `work id × citation year` are invalid.
   Singular dbt tests must fail loudly on those cases.
5. Entries whose citation year precedes the cited work's publication year have
   negative age and cannot contribute to the metric. Exclude them explicitly
   and expose them through a singular dbt test with `severity: warn`; prod
   validation records their count. They are diagnosed upstream metadata
   anomalies, not evidence of negative citation age.

Unexpected warehouse or SQL failures propagate untouched.

## 8. dbt configuration and development behavior

Add the two explicit citation-year vars from §3b to `dbt_project.yml`.

The existing 2012–2016 publication-year dev slice remains because it is the
Q3 analytical cohort and a cheap structural development target. It is not a
representative Q2 sample: a cited-age distribution requires cited works from
all publication vintages back to the corpus boundary.

Consequences:

- dev Q2 builds validate SQL shape, model contracts, and invariants;
- dev Q2 values must not be presented as previews of prod values;
- analytical validation of Q2 requires a prod build over the full
  `silver_works` population;
- developers may override the citation-year vars for faster focused checks,
  but prod uses the pinned defaults.

The shared `half_life_cohort_min` / `half_life_cohort_max` names become false
after Q2 removal. Rename them to `gini_cohort_min` / `gini_cohort_max` and
update Q3 references without changing Q3's 2012–2016 behavior.

No extraction, bronze, staging, silver, Terraform, dependency, or IAM change
is required.

## 9. Test contracts

Contracts are added to `dbt/models/gold/_gold.yml` before model SQL.

### 9a. Generic model and column tests

- unique combination of `citation_year`, `cited_group`;
- non-null on every column;
- accepted values for `cited_group`: `ai`, `cv_pr`, `rest_cs`;
- citation year in the inclusive configured range;
- `citation_events >= 1`;
- `cited_works >= 1`;
- `cited_works <= citation_events`;
- every age quantile `>= 0`;
- every recency share in `[0, 1]`.

### 9b. Singular invariants

- every configured citation year has exactly the three expected group rows;
- `p25_citation_age <= median_citation_age <= p75_citation_age`;
- `share_age_lte_2 <= share_age_lte_5 <= share_age_lte_10`;
- for every `citation_year × cited_group`, `citation_events` reconciles exactly
  to an independently grouped eligible source total;
- for every `citation_year × cited_group`, `cited_works` reconciles exactly to
  an independently grouped eligible distinct-work total;
- no null years/counts, negative counts, or duplicate work/year entries enter
  the configured source slice;
- negative-age entries are visible through the warning diagnostic specified in
  §7.

### 9c. Deterministic metric unit test

A dbt unit fixture pins the core analytical calculation independently of the
population-level invariants. It must cover:

- uneven positive citation weights;
- exact cumulative-weight threshold crossings for p25, median, and p75;
- distinct-work counting rather than event counting;
- all three recency-share boundaries with distinct expected values;
- AI, CV/PR, and null-subfield-to-`rest_cs` classification.

The expected quantiles and shares are literal fixture outputs, not recomputed
with the model's implementation logic.

### 9d. Prod reconciliation

Before approval:

1. Recompute total eligible citation events directly from `silver_works` for
   each configured citation year.
2. Reconcile the three-group partition to those totals exactly.
3. Reconcile distinct cited-work totals exactly.
4. Record the count and event weight of excluded negative-age entries.
5. Inspect all four annual series for missing years, discontinuities, and
   suspicious boundary behavior.
6. Confirm 2026 is absent and 2012–2025 are present.
7. Run the complete dbt test suite in dev and prod.

Exact reconciliation values are evidence produced by implementation, not
hard-coded expectations in this design.

## 10. Removal and deployment contract

Implementation removes:

- `dbt/models/gold/int_paper_half_life.sql`;
- `dbt/models/gold/gold_citation_half_life_by_subfield.sql`;
- their entries and tests in `dbt/models/gold/_gold.yml`;
- Q2-specific comments and variables that describe the removed contract.

The archived design is not edited.

Deleting dbt model files does not delete already materialized BigQuery
relations. Deployment therefore proceeds in this order:

1. Build and test `gold_citation_age_by_year` in dev.
2. Build and reconcile it in prod.
3. Confirm Dagster's freshly parsed manifest contains the new model and not
   the removed models.
4. Explicitly drop the obsolete `int_paper_half_life` view and
   `gold_citation_half_life_by_subfield` table from both dev and prod datasets.
5. Re-run definitions validation and the warehouse staleness preflight.

Only those four fully qualified dev/prod relations are cleanup targets. No
wildcard or dataset-wide cleanup is permitted.

## 11. Freshness contract

Q2 is a **full-corpus analytical snapshot through citation year 2025**. It is
not covered by the automated monthly current-year freshness promise.

“Snapshot” means the current landed state of every publication shard, not one
instantaneous source read. Extraction completed year shards at different
times, and provenance remains year-grained in the existing manifests. The
gold model must not fabricate a single `as_of` timestamp.

`counts_by_year` is stored on the cited work. A citation received in 2026 by a
work published in 1990 changes the 1990 publication shard, not the 2026 shard.
Refreshing only the current publication-year shard therefore cannot produce a
complete new citation year or fully absorb retrospective OpenAlex corrections.

The existing automation remains unchanged:

- monthly invalidation refreshes only `OPENALEX_END_YEAR`;
- convergence and warehouse staleness retain their current contracts;
- a warehouse rebuild may rematerialize Q2, but that does not imply that all
  historical citation histories were refreshed.

Advancing `citation_age_year_max` requires:

1. a deliberate manual full-corpus re-extraction;
2. bronze ingestion and upload convergence for every publication shard;
3. an explicit var change;
4. a prod rebuild and the reconciliation in §9d.

Automating that full-corpus refresh or implementing record-level incremental
updates is out of scope. The dashboard must label Q2 with its citation-year
coverage and must not imply live current-year freshness.

## 12. Interpretation and presentation contract

Preferred language:

- "citation age";
- "citation recency";
- "median age of cited AI, CV/PR, and rest-of-CS works";
- "cited half-life" only when immediately defined as the citation-weighted
  median age used here.

Do not claim that a younger cited-work distribution proves faster intrinsic
obsolescence. The measure combines at least:

- changing citation preferences;
- persistence or decay of attention;
- rapid growth in the available literature;
- changes in subfield composition and OpenAlex coverage.

The three-way comparison is the headline because it exposes the CV/PR
classification judgment rather than hiding it inside a composite. Q1 provides
essential publication-growth context. The dashboard should show all three
annual series, volume context, and the partial current-year exclusion.

This is population-level descriptive analysis over the extracted OpenAlex
corpus, not a random sample. Sampling confidence intervals are therefore not
part of the contract; source coverage and classification uncertainty are the
relevant limitations.

## 13. Out of scope

- citing-side reference-list age;
- re-extracting reference ids or resolving referenced-work metadata;
- a growth-standardized or causal obsolescence model;
- strict/broad composite citation-age outputs;
- subfield-standardized group comparisons;
- automated full-corpus citation-history refresh;
- changes to Q1;
- changes to Q3 beyond renaming its cohort vars;
- dashboard implementation.

Q3's proposed replacement contract is in
`docs/gold-q3-revisit-design.md`. The Q2 revision itself changed nothing in Q3
beyond the cohort var rename.
