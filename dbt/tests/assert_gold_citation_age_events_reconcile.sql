-- Every cited-work group's positive citation-event weight must reconcile
-- exactly to an independently grouped eligible silver source slice after
-- negative-age entries are excluded. The explicit source-side oracle compares
-- both the classification buckets and exhaustive totals at the published grain.
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
        sum(entry.cited_by_count) as citation_events
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
        citation_events
    from {{ ref('gold_citation_age_by_year') }}

)

select
    coalesce(source_totals.citation_year, gold_totals.citation_year) as citation_year,
    coalesce(source_totals.cited_group, gold_totals.cited_group)     as cited_group,
    source_totals.citation_events                                    as source_events,
    gold_totals.citation_events                                      as gold_events
from source_totals
full outer join gold_totals
    using (citation_year, cited_group)
where source_totals.citation_events is distinct from gold_totals.citation_events
