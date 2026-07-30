-- The subfield and pooled-group relations are exhaustive partitions of the
-- same papers. Additive measures therefore reconcile exactly at cohort/age.
with subfield_totals as (

    select
        publication_year,
        citation_age,
        sum(n_papers) as n_papers,
        sum(total_citations) as total_citations
    from {{ ref('gold_citation_gini_by_subfield') }}
    group by publication_year, citation_age

),

group_totals as (

    select
        publication_year,
        citation_age,
        sum(n_papers) as n_papers,
        sum(total_citations) as total_citations
    from {{ ref('gold_citation_gini_by_group') }}
    group by publication_year, citation_age

)

select
    coalesce(subfield_totals.publication_year, group_totals.publication_year)
        as publication_year,
    coalesce(subfield_totals.citation_age, group_totals.citation_age)
        as citation_age,
    subfield_totals.n_papers as subfield_n_papers,
    group_totals.n_papers as group_n_papers,
    subfield_totals.total_citations as subfield_total_citations,
    group_totals.total_citations as group_total_citations
from subfield_totals
full outer join group_totals
    using (publication_year, citation_age)
where subfield_totals.n_papers is distinct from group_totals.n_papers
   or subfield_totals.total_citations is distinct from group_totals.total_citations
