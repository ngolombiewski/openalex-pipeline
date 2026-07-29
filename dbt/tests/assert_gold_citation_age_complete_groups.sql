-- Every configured citation year must publish exactly the three expected
-- mutually exclusive cited-work groups. Generic uniqueness, accepted-values,
-- and range tests diagnose duplicates or unexpected keys separately.
with expected as (

    select
        citation_year,
        cited_group
    from unnest(
        generate_array(
            {{ var('citation_age_year_min') }},
            {{ var('citation_age_year_max') }}
        )
    ) as citation_year
    cross join unnest(['ai', 'cv_pr', 'rest_cs']) as cited_group

),

actual as (

    select citation_year, cited_group
    from {{ ref('gold_citation_age_by_year') }}

)

select
    coalesce(expected.citation_year, actual.citation_year) as citation_year,
    coalesce(expected.cited_group, actual.cited_group)     as cited_group
from expected
full outer join actual
    using (citation_year, cited_group)
where expected.citation_year is null
   or actual.citation_year is null
