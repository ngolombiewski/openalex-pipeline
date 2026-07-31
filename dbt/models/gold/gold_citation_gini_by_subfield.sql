-- Q3 — The Winner's Game, primary subfield comparison.
--
-- Grain: subfield_id × publication_year × citation_age. Each citation_age is
-- the cumulative fixed window of complete calendar years 1..citation_age
-- following publication. Every paper remains in every observable window,
-- including papers with no citations. The synthetic __unclassified__ bucket
-- preserves the silver denominator but is not a real CS subfield.
--
-- Gini is computed from exact integer value frequencies. Top-k shares take
-- ceil(k * n_papers) from the full cohort (including zeros); allocating the
-- required count from a tied boundary frequency makes the result independent
-- of paper ordering. Age 0 is excluded from the measures and exposed through
-- age0_citation_share and zero_share_including_age0.

with paper_windows as (

    {{ q3_paper_windows() }}

),

subfield_windows as (

    select
        coalesce(primary_topic_subfield_id, '__unclassified__') as subfield_id,
        publication_year,
        citation_age,
        window_citations,
        age0_citations
    from paper_windows

),

label_mapping as (

    select
        coalesce(primary_topic_subfield_id, '__unclassified__') as subfield_id,
        case
            when primary_topic_subfield_id is null then 'Unclassified'
            else coalesce(
                max(primary_topic_subfield_display_name),
                primary_topic_subfield_id
            )
        end as subfield_display_name,
        logical_or(is_ai_strict) as is_ai_strict,
        logical_or(is_ai_broad) as is_ai_broad
    from {{ ref('silver_works') }}
    where publication_year between
            {{ var('gini_cohort_min') }}
            and {{ var('gini_citation_year_max') }} - 1
    group by primary_topic_subfield_id

),

cell_diagnostics as (

    select
        subfield_id,
        publication_year,
        citation_age,
        count(*) as n_papers,
        sum(window_citations) as total_citations,
        countif(window_citations = 0) as zero_papers,
        countif(window_citations + age0_citations = 0)
            as zero_papers_including_age0,
        sum(age0_citations) as age0_citations,
        sum(window_citations + age0_citations) as citations_including_age0
    from subfield_windows
    group by subfield_id, publication_year, citation_age

),

value_frequencies as (

    select
        subfield_id,
        publication_year,
        citation_age,
        window_citations,
        count(*) as n_papers_at_value
    from subfield_windows
    group by subfield_id, publication_year, citation_age, window_citations

),

frequency_ranks as (

    select
        *,
        sum(n_papers_at_value) over (
            partition by subfield_id, publication_year, citation_age
        ) as n_papers,
        sum(window_citations * n_papers_at_value) over (
            partition by subfield_id, publication_year, citation_age
        ) as total_citations,
        coalesce(
            sum(n_papers_at_value) over (
                partition by subfield_id, publication_year, citation_age
                order by window_citations
                rows between unbounded preceding and 1 preceding
            ),
            0
        ) as papers_below,
        coalesce(
            sum(n_papers_at_value) over (
                partition by subfield_id, publication_year, citation_age
                order by window_citations desc
                rows between unbounded preceding and 1 preceding
            ),
            0
        ) as papers_above
    from value_frequencies

),

headline_metrics as (

    select
        subfield_id,
        publication_year,
        citation_age,
        any_value(n_papers) as n_papers,
        any_value(total_citations) as total_citations,
        sum(
            window_citations
            * n_papers_at_value
            * (2 * papers_below + n_papers_at_value - n_papers)
        ) as gini_numerator,
        sum(
            window_citations
            * least(
                n_papers_at_value,
                greatest(div(n_papers + 99, 100) - papers_above, 0)
            )
        ) as top1_citations,
        sum(
            window_citations
            * least(
                n_papers_at_value,
                greatest(div(n_papers + 19, 20) - papers_above, 0)
            )
        ) as top5_citations,
        sum(
            window_citations
            * least(
                n_papers_at_value,
                greatest(div(n_papers + 9, 10) - papers_above, 0)
            )
        ) as top10_citations
    from frequency_ranks
    group by subfield_id, publication_year, citation_age

),

cited_frequency_ranks as (

    select
        *,
        sum(n_papers_at_value) over (
            partition by subfield_id, publication_year, citation_age
        ) as n_cited_papers,
        sum(window_citations * n_papers_at_value) over (
            partition by subfield_id, publication_year, citation_age
        ) as cited_citations,
        coalesce(
            sum(n_papers_at_value) over (
                partition by subfield_id, publication_year, citation_age
                order by window_citations
                rows between unbounded preceding and 1 preceding
            ),
            0
        ) as cited_papers_below
    from value_frequencies
    where window_citations > 0

),

cited_only_metrics as (

    select
        subfield_id,
        publication_year,
        citation_age,
        sum(
            window_citations
            * n_papers_at_value
            * (
                2 * cited_papers_below
                + n_papers_at_value
                - n_cited_papers
            )
        ) / nullif(
            any_value(n_cited_papers) * any_value(cited_citations),
            0
        ) as gini_cited_only
    from cited_frequency_ranks
    group by subfield_id, publication_year, citation_age

)

select
    cell_diagnostics.publication_year,
    cell_diagnostics.subfield_id,
    label_mapping.subfield_display_name,
    label_mapping.is_ai_strict,
    label_mapping.is_ai_broad,
    cell_diagnostics.citation_age,
    cell_diagnostics.n_papers,
    cell_diagnostics.total_citations,
    cell_diagnostics.zero_papers / cell_diagnostics.n_papers as zero_share,
    headline_metrics.gini_numerator / nullif(
        headline_metrics.n_papers * headline_metrics.total_citations,
        0
    ) as gini,
    cited_only_metrics.gini_cited_only,
    headline_metrics.top1_citations
        / nullif(headline_metrics.total_citations, 0) as top1_share,
    headline_metrics.top5_citations
        / nullif(headline_metrics.total_citations, 0) as top5_share,
    headline_metrics.top10_citations
        / nullif(headline_metrics.total_citations, 0) as top10_share,
    cell_diagnostics.age0_citations
        / nullif(cell_diagnostics.citations_including_age0, 0)
        as age0_citation_share,
    cell_diagnostics.zero_papers_including_age0
        / cell_diagnostics.n_papers as zero_share_including_age0
from cell_diagnostics
inner join headline_metrics
    using (subfield_id, publication_year, citation_age)
left join cited_only_metrics
    using (subfield_id, publication_year, citation_age)
inner join label_mapping
    using (subfield_id)
