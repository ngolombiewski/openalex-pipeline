-- The pinned AI subfield must appear in every cohort that the intersection of
-- the independent Q3 and selected corpus bounds can build.
with expected as (

    select publication_year
    from unnest(
        generate_array(
            greatest(
                {{ var('gini_cohort_min') }},
                {{ var('year_min') }}
            ),
            least(
                {{ var('gini_citation_year_max') }} - 1,
                {{ var('year_max') }}
            )
        )
    ) as publication_year

),

actual as (

    select distinct publication_year
    from {{ ref('gold_citation_gini_by_subfield') }}
    where subfield_id = '{{ var("subfield_ai") }}'

)

select expected.publication_year
from expected
left join actual using (publication_year)
where actual.publication_year is null
