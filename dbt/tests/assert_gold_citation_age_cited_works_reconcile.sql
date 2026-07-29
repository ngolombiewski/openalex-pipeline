-- Each cited work belongs to exactly one group. Compare distinct-work counts at
-- the full citation_year × cited_group grain so an output-side redistribution
-- cannot hide behind a correct all-groups total.
with source_totals as (

    select
        entry.year as citation_year,
        case
            when works.primary_topic_subfield_id = '{{ var("subfield_ai") }}'
                then 'ai'
            when works.primary_topic_subfield_id = '{{ var("subfield_cv_pr") }}'
                then 'cv_pr'
            else 'rest_cs'
        end        as cited_group,
        count(distinct works.id) as cited_works
    from {{ ref('silver_works') }} as works
    cross join unnest(works.counts_by_year) as entry
    where entry.year between
            {{ var('citation_age_year_min') }}
            and {{ var('citation_age_year_max') }}
      and entry.year >= works.publication_year
      and entry.cited_by_count > 0
    group by entry.year, cited_group

),

gold_totals as (

    select
        citation_year,
        cited_group,
        cited_works
    from {{ ref('gold_citation_age_by_year') }}

)

select
    coalesce(source_totals.citation_year, gold_totals.citation_year) as citation_year,
    coalesce(source_totals.cited_group, gold_totals.cited_group)     as cited_group,
    source_totals.cited_works                                        as source_cited_works,
    gold_totals.cited_works                                          as gold_cited_works
from source_totals
full outer join gold_totals
    using (citation_year, cited_group)
where source_totals.cited_works is distinct from gold_totals.cited_works
