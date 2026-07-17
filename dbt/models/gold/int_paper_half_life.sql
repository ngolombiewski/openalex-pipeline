{{ config(materialized='view') }}

-- Per-paper citation half-life over the Q2/Q3 cohort
-- (docs/design-archive/gold-design.md §3).
-- One row per *cited* cohort paper. Zero-citation papers have no half-life and
-- carry no row here; the gold model reports them via uncited_rate. Materialized
-- as a view: single consumer, but queryable for debugging.
--
-- half_life = citation age at which cumulative citations first reach 50% of
-- the paper's observed total, linearly interpolated between the observed age
-- below the crossing and the crossing age. If the first observed age already
-- reaches 50%, half_life snaps to that age (no earlier observation to
-- interpolate from).

with cohort as (

    select id, publication_year, primary_topic_subfield_id, counts_by_year
    from {{ ref('silver_works') }}
    where publication_year
        between {{ var('half_life_cohort_min') }} and {{ var('half_life_cohort_max') }}

),

-- One row per (paper, citing year), keyed by citation age. Pre-publication
-- entries (age < 0) are anomalies, not signal — dropped (design §3a). The
-- cites > 0 guard drops empty entries and guarantees a nonzero interpolation
-- divisor (prefix sums strictly increase across kept rows).
citation_years as (

    select
        cohort.id,
        cohort.primary_topic_subfield_id,
        entry.year - cohort.publication_year as age,
        entry.cited_by_count                 as cites
    from cohort
    cross join unnest(cohort.counts_by_year) as entry
    where entry.year >= cohort.publication_year
      and entry.cited_by_count > 0

),

cumulated as (

    select
        id,
        primary_topic_subfield_id,
        age,
        sum(cites) over (partition by id order by age) as cum_cites,
        sum(cites) over (partition by id)              as total_cites,
        lag(age)   over (partition by id order by age) as prev_age,
        sum(cites) over (
            partition by id order by age
            rows between unbounded preceding and 1 preceding
        )                                              as prev_cum
    from citation_years

)

-- Keep only crossing candidates, then the *first* crossing per paper. At that
-- row prev_cum < 0.5 * total_cites by minimality, so the interpolation fraction
-- lands in (0, 1].
select
    id,
    primary_topic_subfield_id,
    case
        when prev_age is null then age * 1.0
        else prev_age
             + (age - prev_age)
             * (0.5 * total_cites - prev_cum) / (cum_cites - prev_cum)
    end as half_life
from cumulated
where cum_cites >= 0.5 * total_cites
qualify row_number() over (partition by id order by age) = 1
