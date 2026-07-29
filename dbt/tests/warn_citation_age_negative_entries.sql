{{ config(severity='warn') }}

-- A positive citation count before the cited work's publication year is an
-- upstream metadata anomaly. Q2 excludes it; this warning keeps the excluded
-- row count and event weight visible during prod validation.
select
    works.id,
    works.publication_year,
    entry.year                                      as citation_year,
    entry.year - works.publication_year             as citation_age,
    entry.cited_by_count                            as citation_events
from {{ ref('silver_works') }} as works
cross join unnest(works.counts_by_year) as entry
where entry.year between
        {{ var('citation_age_year_min') }}
        and {{ var('citation_age_year_max') }}
  and entry.year < works.publication_year
  and entry.cited_by_count > 0
