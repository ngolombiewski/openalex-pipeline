-- For the finite-sample estimator used by Q3, the full-population Gini is
-- exactly the zero share plus the cited-population Gini scaled by cited share.
with measures as (

    select
        'subfield' as model_name,
        cast(subfield_id as string) as grain_key,
        publication_year,
        citation_age,
        total_citations,
        zero_share,
        gini,
        gini_cited_only
    from {{ ref('gold_citation_gini_by_subfield') }}

    union all

    select
        'group',
        cited_group,
        publication_year,
        citation_age,
        total_citations,
        zero_share,
        gini,
        gini_cited_only
    from {{ ref('gold_citation_gini_by_group') }}

)

select *
from measures
where (total_citations = 0 and (gini is not null or gini_cited_only is not null))
   or (total_citations > 0 and (gini is null or gini_cited_only is null))
   or (
        gini is not null
        and gini_cited_only is not null
        and abs(
            gini - (zero_share + (1 - zero_share) * gini_cited_only)
        ) > 1e-9
    )
