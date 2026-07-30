-- Extending a cumulative window cannot remove citations or turn a zero paper
-- back into a cited one.
with measures as (

    select
        'subfield' as model_name,
        cast(subfield_id as string) as grain_key,
        publication_year,
        citation_age,
        total_citations,
        zero_share
    from {{ ref('gold_citation_gini_by_subfield') }}

    union all

    select
        'group',
        cited_group,
        publication_year,
        citation_age,
        total_citations,
        zero_share
    from {{ ref('gold_citation_gini_by_group') }}

),

with_previous as (

    select
        *,
        lag(total_citations) over (
            partition by model_name, grain_key, publication_year
            order by citation_age
        ) as previous_total_citations,
        lag(zero_share) over (
            partition by model_name, grain_key, publication_year
            order by citation_age
        ) as previous_zero_share
    from measures

)

select *
from with_previous
where total_citations < previous_total_citations
   or zero_share > previous_zero_share
