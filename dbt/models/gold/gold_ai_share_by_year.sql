-- Q1 — The Takeover: AI's share of CS works per publication year, long over
-- the two ablation variants so the dashboard toggle is a filter, not a pivot.
-- No cohort restriction: a within-year ratio is immune to the citation-window
-- and age confounds (docs/design-archive/gold-design.md §2). Denominator is
-- every silver work in the year (all works are CS by the extraction filter;
-- 0 null subfields).

with by_year as (

    select
        publication_year,
        count(*)              as cs_works,
        countif(is_ai_strict) as ai_strict_works,
        countif(is_ai_broad)  as ai_broad_works
    from {{ ref('silver_works') }}
    group by publication_year

),

long as (

    select publication_year, 'strict' as variant, cs_works, ai_strict_works as ai_works
    from by_year

    union all

    select publication_year, 'broad' as variant, cs_works, ai_broad_works as ai_works
    from by_year

)

select
    publication_year,
    variant,
    cs_works,
    ai_works,
    ai_works / cs_works                            as share,  -- cs_works >= 1 by construction (grouped)
    publication_year = {{ var('partial_year') }}   as is_partial_year
from long
