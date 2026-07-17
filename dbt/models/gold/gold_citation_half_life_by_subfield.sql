-- Q2 — The Shelf Life: citation half-life per CS subfield over the 2012–2016
-- cohort (docs/design-archive/gold-design.md §3). Grain: one row per subfield,
-- with strict/broad AI labels identifying the AI subfields. The published
-- medians cannot be pooled downstream into AI-vs-rest statistics; that requires
-- a separate paper-level aggregation. n_cited / uncited_rate give the context
-- the half-life must be read in: papers with no observable citations (~61%
-- corpus-wide) have no half-life and are excluded from the percentiles, not
-- from n_papers.

with cohort as (

    select
        id,
        primary_topic_subfield_id,
        primary_topic_subfield_display_name,
        is_ai_strict,
        is_ai_broad
    from {{ ref('silver_works') }}
    where publication_year
        between {{ var('half_life_cohort_min') }} and {{ var('half_life_cohort_max') }}

),

half_lives as (

    select id, primary_topic_subfield_id, half_life
    from {{ ref('int_paper_half_life') }}

),

-- percentile_cont is analytic-only in BigQuery; the distinct collapses the
-- per-row windows to one row per subfield. Exact, not approximate.
percentiles as (

    select distinct
        primary_topic_subfield_id,
        percentile_cont(half_life, 0.25) over (partition by primary_topic_subfield_id) as p25_half_life,
        percentile_cont(half_life, 0.5)  over (partition by primary_topic_subfield_id) as median_half_life,
        percentile_cont(half_life, 0.75) over (partition by primary_topic_subfield_id) as p75_half_life
    from half_lives

),

-- The AI flags are functions of the subfield id, so logical_or reads the
-- constant subfield-level label, not a mixture.
counts as (

    select
        cohort.primary_topic_subfield_id,
        any_value(cohort.primary_topic_subfield_display_name) as subfield_display_name,
        logical_or(cohort.is_ai_strict)                       as is_ai_strict,
        logical_or(cohort.is_ai_broad)                        as is_ai_broad,
        count(*)                                              as n_papers,
        count(half_lives.id)                                  as n_cited
    from cohort
    left join half_lives
        on cohort.id = half_lives.id
    group by cohort.primary_topic_subfield_id

)

select
    counts.primary_topic_subfield_id     as subfield_id,
    counts.subfield_display_name,
    counts.is_ai_strict,
    counts.is_ai_broad,
    counts.n_papers,
    counts.n_cited,
    1 - counts.n_cited / counts.n_papers as uncited_rate,
    percentiles.median_half_life,
    percentiles.p25_half_life,
    percentiles.p75_half_life
from counts
left join percentiles
    on counts.primary_topic_subfield_id = percentiles.primary_topic_subfield_id
