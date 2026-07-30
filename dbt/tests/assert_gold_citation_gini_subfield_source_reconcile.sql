-- Independent source oracle for every published subfield/cohort/age cell. This
-- deliberately does not call the shared model macro.
with eligible_papers as (

    select
        id,
        publication_year,
        coalesce(primary_topic_subfield_id, '__unclassified__') as subfield_id,
        counts_by_year
    from {{ ref('silver_works') }}
    where publication_year between
            {{ var('gini_cohort_min') }}
            and {{ var('gini_citation_year_max') }} - 1

),

paper_windows as (

    select
        eligible_papers.id,
        eligible_papers.publication_year,
        eligible_papers.subfield_id,
        citation_age,
        sum(
            if(
                entry.year > eligible_papers.publication_year,
                entry.cited_by_count,
                0
            )
        ) as window_citations,
        sum(
            if(
                entry.year = eligible_papers.publication_year,
                entry.cited_by_count,
                0
            )
        ) as age0_citations
    from eligible_papers
    cross join unnest(
        generate_array(
            1,
            {{ var('gini_citation_year_max') }} - publication_year
        )
    ) as citation_age
    left join unnest(eligible_papers.counts_by_year) as entry
        on entry.year between
            eligible_papers.publication_year
            and eligible_papers.publication_year + citation_age
       and entry.cited_by_count > 0
    group by
        eligible_papers.id,
        eligible_papers.publication_year,
        eligible_papers.subfield_id,
        citation_age

),

expected as (

    select
        subfield_id,
        publication_year,
        citation_age,
        count(*) as n_papers,
        sum(window_citations) as total_citations,
        countif(window_citations = 0) as zero_papers,
        countif(window_citations + age0_citations = 0) as zero_papers_including_age0,
        sum(age0_citations) as age0_citations,
        sum(window_citations + age0_citations) as citations_including_age0
    from paper_windows
    group by subfield_id, publication_year, citation_age

),

actual as (

    select
        subfield_id,
        publication_year,
        citation_age,
        n_papers,
        total_citations,
        cast(round(zero_share * n_papers) as int64) as zero_papers,
        cast(round(zero_share_including_age0 * n_papers) as int64)
            as zero_papers_including_age0,
        age0_citation_share
    from {{ ref('gold_citation_gini_by_subfield') }}

),

reconciled as (

    select
        coalesce(expected.subfield_id, actual.subfield_id) as subfield_id,
        coalesce(expected.publication_year, actual.publication_year) as publication_year,
        coalesce(expected.citation_age, actual.citation_age) as citation_age,
        expected.n_papers as expected_n_papers,
        actual.n_papers as actual_n_papers,
        expected.total_citations as expected_total_citations,
        actual.total_citations as actual_total_citations,
        expected.zero_papers as expected_zero_papers,
        actual.zero_papers as actual_zero_papers,
        expected.zero_papers_including_age0 as expected_zero_papers_including_age0,
        actual.zero_papers_including_age0 as actual_zero_papers_including_age0,
        expected.age0_citations
            / nullif(expected.citations_including_age0, 0) as expected_age0_share,
        actual.age0_citation_share as actual_age0_share
    from expected
    full outer join actual
        using (subfield_id, publication_year, citation_age)

)

select *
from reconciled
where expected_n_papers is distinct from actual_n_papers
   or expected_total_citations is distinct from actual_total_citations
   or expected_zero_papers is distinct from actual_zero_papers
   or expected_zero_papers_including_age0
        is distinct from actual_zero_papers_including_age0
   or (expected_age0_share is null) != (actual_age0_share is null)
   or (
        expected_age0_share is not null
        and abs(expected_age0_share - actual_age0_share) > 1e-12
    )
