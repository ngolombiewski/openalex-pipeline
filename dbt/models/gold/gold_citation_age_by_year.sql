-- Q2 — Citation-weighted age of cited works by citation year.
-- Grain: citation_year × cited_group, where cited_group is the mutually
-- exclusive partition ai / cv_pr / rest_cs. Classification applies to the
-- cited work, not the unknown citing work.
--
-- counts_by_year is already annual, so citation ages and weighted quantiles
-- are discrete integer years. The qth quantile is the smallest age whose
-- cumulative citation-event weight reaches q of the group/year total; no
-- within-year interpolation is supported by the source.

with eligible_events as (

    select
        works.id,
        entry.year - works.publication_year as citation_age,
        entry.year                          as citation_year,
        case
            when works.primary_topic_subfield_id = '{{ var("subfield_ai") }}'
                then 'ai'
            when works.primary_topic_subfield_id = '{{ var("subfield_cv_pr") }}'
                then 'cv_pr'
            else 'rest_cs'
        end                                 as cited_group,
        entry.cited_by_count                as citation_events
    from {{ ref('silver_works') }} as works
    cross join unnest(works.counts_by_year) as entry
    where entry.year between
            {{ var('citation_age_year_min') }}
            and {{ var('citation_age_year_max') }}
      and entry.year >= works.publication_year
      and entry.cited_by_count > 0

),

age_bins as (

    select
        citation_year,
        cited_group,
        citation_age,
        sum(citation_events) as citation_events
    from eligible_events
    group by citation_year, cited_group, citation_age

),

weighted_age_bins as (

    select
        citation_year,
        cited_group,
        citation_age,
        citation_events,
        sum(citation_events) over (
            partition by citation_year, cited_group
        ) as total_citation_events,
        sum(citation_events) over (
            partition by citation_year, cited_group
            order by citation_age
            rows between unbounded preceding and current row
        ) as cumulative_citation_events
    from age_bins

),

distribution_summary as (

    select
        citation_year,
        cited_group,
        any_value(total_citation_events) as citation_events,
        min(
            if(
                4 * cumulative_citation_events >= total_citation_events,
                citation_age,
                null
            )
        ) as p25_citation_age,
        min(
            if(
                2 * cumulative_citation_events >= total_citation_events,
                citation_age,
                null
            )
        ) as median_citation_age,
        min(
            if(
                4 * cumulative_citation_events >= 3 * total_citation_events,
                citation_age,
                null
            )
        ) as p75_citation_age,
        sum(if(citation_age <= 2, citation_events, 0))
            / any_value(total_citation_events) as share_age_lte_2,
        sum(if(citation_age <= 5, citation_events, 0))
            / any_value(total_citation_events) as share_age_lte_5,
        sum(if(citation_age <= 10, citation_events, 0))
            / any_value(total_citation_events) as share_age_lte_10
    from weighted_age_bins
    group by citation_year, cited_group

),

work_counts as (

    select
        citation_year,
        cited_group,
        count(distinct id) as cited_works
    from eligible_events
    group by citation_year, cited_group

)

select
    distribution_summary.citation_year,
    distribution_summary.cited_group,
    distribution_summary.citation_events,
    work_counts.cited_works,
    distribution_summary.p25_citation_age,
    distribution_summary.median_citation_age,
    distribution_summary.p75_citation_age,
    distribution_summary.share_age_lte_2,
    distribution_summary.share_age_lte_5,
    distribution_summary.share_age_lte_10
from distribution_summary
inner join work_counts
    using (citation_year, cited_group)
