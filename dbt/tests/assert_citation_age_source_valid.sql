-- Source-array corruption is loud. A null year is invalid anywhere; within
-- the configured citation-year slice, counts must be non-null/non-negative and
-- each work may carry at most one entry per year.
with entries as (

    select
        works.id,
        entry.year,
        entry.cited_by_count
    from {{ ref('silver_works') }} as works
    cross join unnest(works.counts_by_year) as entry

),

invalid_entries as (

    select
        'null_year' as anomaly,
        id,
        year,
        cited_by_count
    from entries
    where year is null

    union all

    select
        case
            when cited_by_count is null then 'null_count'
            else 'negative_count'
        end as anomaly,
        id,
        year,
        cited_by_count
    from entries
    where year between
            {{ var('citation_age_year_min') }}
            and {{ var('citation_age_year_max') }}
      and (cited_by_count is null or cited_by_count < 0)

),

duplicate_entries as (

    select
        'duplicate_work_year' as anomaly,
        id,
        year,
        cast(null as int64) as cited_by_count
    from entries
    where year between
            {{ var('citation_age_year_min') }}
            and {{ var('citation_age_year_max') }}
    group by id, year
    having count(*) > 1

)

select * from invalid_entries
union all
select * from duplicate_entries
