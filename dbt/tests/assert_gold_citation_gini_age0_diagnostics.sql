-- Including age 0 can only reduce the zero share. As the cumulative endpoint
-- advances, both age-0 diagnostics are non-increasing.
with measures as (

    select
        'subfield' as model_name,
        cast(subfield_id as string) as grain_key,
        publication_year,
        citation_age,
        zero_share,
        age0_citation_share,
        zero_share_including_age0
    from {{ ref('gold_citation_gini_by_subfield') }}

    union all

    select
        'group',
        cited_group,
        publication_year,
        citation_age,
        zero_share,
        age0_citation_share,
        zero_share_including_age0
    from {{ ref('gold_citation_gini_by_group') }}

),

with_previous as (

    select
        *,
        lag(zero_share_including_age0) over (
            partition by model_name, grain_key, publication_year
            order by citation_age
        ) as previous_zero_share_including_age0,
        lag(age0_citation_share) over (
            partition by model_name, grain_key, publication_year
            order by citation_age
        ) as previous_age0_citation_share
    from measures

)

select *
from with_previous
where zero_share_including_age0 > zero_share
   or zero_share_including_age0 > previous_zero_share_including_age0
   or (
        age0_citation_share is not null
        and previous_age0_citation_share is not null
        and age0_citation_share > previous_age0_citation_share
    )
