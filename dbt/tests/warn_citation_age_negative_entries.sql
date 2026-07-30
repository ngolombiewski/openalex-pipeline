{{ config(severity='warn') }}

-- A positive citation count before the cited work's publication year is an
-- upstream metadata anomaly. Q2 and Q3 exclude it; this shared warning covers
-- the union of their active citation-year ranges.
select
    works.id,
    works.publication_year,
    entry.year                                      as citation_year,
    entry.year - works.publication_year             as citation_age,
    entry.cited_by_count                            as citation_events
from {{ ref('silver_works') }} as works
cross join unnest(works.counts_by_year) as entry
where entry.year between
        least(
            {{ var('citation_age_year_min') }},
            {{ var('gini_cohort_min') }}
        )
        and greatest(
            {{ var('citation_age_year_max') }},
            {{ var('gini_citation_year_max') }}
        )
  and entry.year < works.publication_year
  and entry.cited_by_count > 0
