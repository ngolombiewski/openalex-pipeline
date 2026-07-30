{% macro q3_paper_windows() %}

    select
        works.id,
        works.publication_year,
        works.primary_topic_subfield_id,
        works.primary_topic_subfield_display_name,
        works.is_ai_strict,
        works.is_ai_broad,
        case
            when works.primary_topic_subfield_id = '{{ var("subfield_ai") }}'
                then 'ai'
            when works.primary_topic_subfield_id = '{{ var("subfield_cv_pr") }}'
                then 'cv_pr'
            else 'rest_cs'
        end as cited_group,
        citation_age,
        sum(
            if(
                entry.year between
                    works.publication_year + 1
                    and works.publication_year + citation_age,
                entry.cited_by_count,
                0
            )
        ) as window_citations,
        sum(
            if(
                entry.year = works.publication_year,
                entry.cited_by_count,
                0
            )
        ) as age0_citations
    from {{ ref('silver_works') }} as works
    cross join unnest(
        generate_array(
            1,
            {{ var('gini_citation_year_max') }} - works.publication_year
        )
    ) as citation_age
    left join unnest(works.counts_by_year) as entry
        on entry.year between
            works.publication_year
            and works.publication_year + citation_age
       and entry.cited_by_count > 0
    where works.publication_year between
            {{ var('gini_cohort_min') }}
            and {{ var('gini_citation_year_max') }} - 1
    group by
        works.id,
        works.publication_year,
        works.primary_topic_subfield_id,
        works.primary_topic_subfield_display_name,
        works.is_ai_strict,
        works.is_ai_broad,
        cited_group,
        citation_age

{% endmacro %}
