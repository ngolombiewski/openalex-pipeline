-- Each built cohort/grain cell publishes the complete observable lifecycle
-- triangle and nothing beyond its configured edge.
with actual as (

    select
        'subfield' as model_name,
        cast(subfield_id as string) as grain_key,
        publication_year,
        citation_age
    from {{ ref('gold_citation_gini_by_subfield') }}

    union all

    select
        'group',
        cited_group,
        publication_year,
        citation_age
    from {{ ref('gold_citation_gini_by_group') }}

),

grain_cohorts as (

    select distinct model_name, grain_key, publication_year
    from actual

),

expected as (

    select
        grain_cohorts.model_name,
        grain_cohorts.grain_key,
        grain_cohorts.publication_year,
        citation_age
    from grain_cohorts
    cross join unnest(
        generate_array(
            1,
            {{ var('gini_citation_year_max') }} - publication_year
        )
    ) as citation_age

)

select
    coalesce(expected.model_name, actual.model_name) as model_name,
    coalesce(expected.grain_key, actual.grain_key) as grain_key,
    coalesce(expected.publication_year, actual.publication_year) as publication_year,
    coalesce(expected.citation_age, actual.citation_age) as citation_age
from expected
full outer join actual
    using (model_name, grain_key, publication_year, citation_age)
where expected.publication_year is null
   or actual.publication_year is null
