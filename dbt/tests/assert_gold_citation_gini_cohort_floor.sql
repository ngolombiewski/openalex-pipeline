-- The rolling source window makes the configured Q3 cohort floor a hard
-- analytical guard, while the built minimum intersects that floor with the
-- selected corpus slice.
with model_minima as (

    select
        'subfield' as model_name,
        min(publication_year) as minimum_publication_year,
        countif(publication_year < {{ var('gini_cohort_min') }}) as below_floor
    from {{ ref('gold_citation_gini_by_subfield') }}

    union all

    select
        'group',
        min(publication_year),
        countif(publication_year < {{ var('gini_cohort_min') }})
    from {{ ref('gold_citation_gini_by_group') }}

)

select *
from model_minima
where below_floor > 0
   or minimum_publication_year is distinct from greatest(
        {{ var('gini_cohort_min') }},
        {{ var('year_min') }}
    )
