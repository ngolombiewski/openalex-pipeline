-- Top-k citation shares are nested. They are undefined together when a cell
-- has no window citations.
with measures as (

    select
        'subfield' as model_name,
        cast(subfield_id as string) as grain_key,
        publication_year,
        citation_age,
        total_citations,
        top1_share,
        top5_share,
        top10_share
    from {{ ref('gold_citation_gini_by_subfield') }}

    union all

    select
        'group',
        cited_group,
        publication_year,
        citation_age,
        total_citations,
        top1_share,
        top5_share,
        top10_share
    from {{ ref('gold_citation_gini_by_group') }}

)

select *
from measures
where (total_citations = 0 and (
        top1_share is not null
        or top5_share is not null
        or top10_share is not null
    ))
   or (total_citations > 0 and (
        top1_share is null
        or top5_share is null
        or top10_share is null
        or top1_share > top5_share
        or top5_share > top10_share
    ))
