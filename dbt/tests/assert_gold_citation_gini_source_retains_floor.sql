-- Sparse arrays cannot prove per-paper coverage, but at least one eligible
-- source array must retain the floor year of the corpus slice actually built.
with bounds as (

    select
        greatest(
            {{ var('gini_cohort_min') }},
            {{ var('year_min') }}
        ) as built_floor,
        least(
            {{ var('gini_citation_year_max') }} - 1,
            {{ var('year_max') }}
        ) as built_ceiling

),

floor_entries as (

    select 1 as present
    from {{ ref('silver_works') }} as works
    cross join bounds
    cross join unnest(works.counts_by_year) as entry
    where works.publication_year between bounds.built_floor and bounds.built_ceiling
      and entry.year = bounds.built_floor
    limit 1

)

select bounds.*
from bounds
where bounds.built_floor <= bounds.built_ceiling
  and not exists (select 1 from floor_entries)
