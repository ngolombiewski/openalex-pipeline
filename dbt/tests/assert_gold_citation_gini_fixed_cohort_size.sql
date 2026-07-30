-- A paper cohort is fixed while citation_age extends its cumulative window.
with measures as (

    select
        'subfield' as model_name,
        cast(subfield_id as string) as grain_key,
        publication_year,
        n_papers
    from {{ ref('gold_citation_gini_by_subfield') }}

    union all

    select
        'group',
        cited_group,
        publication_year,
        n_papers
    from {{ ref('gold_citation_gini_by_group') }}

)

select model_name, grain_key, publication_year
from measures
group by model_name, grain_key, publication_year
having count(distinct n_papers) != 1
