-- Q3 — The Winner's Game: Gini of cited_by_count per CS subfield, over the
-- same 2012–2016 cohort as Q2 (age control, docs/gold-design.md §4).
-- The headline gini *includes* zero-citation papers: the uncited majority vs
-- the cited few is the concentration story, and dropping zeros would
-- understate it. gini_cited_only is the secondary lens (§4c): concentration
-- among papers that got cited at all, disentangled from the uncited-rate —
-- the two ginis rank subfields differently and both matter.
--
-- Gini for x sorted ascending, i = 1..n:
--   gini = sum((2i - n - 1) * x) / (n * sum(x))
-- Ties: row_number orders ties arbitrarily, but equal x contribute the same
-- sum either way, so the result is order-stable.

with cohort as (

    select
        primary_topic_subfield_id,
        primary_topic_subfield_display_name,
        is_ai_strict,
        is_ai_broad,
        cited_by_count
    from {{ ref('silver_works') }}
    where publication_year
        between {{ var('half_life_cohort_min') }} and {{ var('half_life_cohort_max') }}

),

ranked as (

    select
        *,
        row_number()        over (partition by primary_topic_subfield_id order by cited_by_count) as i,
        count(*)            over (partition by primary_topic_subfield_id)                          as n,
        sum(cited_by_count) over (partition by primary_topic_subfield_id)                          as total_citations
    from cohort

),

headline as (

    select
        primary_topic_subfield_id                       as subfield_id,
        any_value(primary_topic_subfield_display_name)  as subfield_display_name,
        logical_or(is_ai_strict)                        as is_ai_strict,
        logical_or(is_ai_broad)                         as is_ai_broad,
        count(*)                                        as n_papers,
        any_value(total_citations)                      as total_citations,
        -- nullif guards an all-zero subfield (gini undefined -> NULL, loudly
        -- odd rather than silently 0)
        sum((2 * i - n - 1) * cited_by_count)
            / nullif(count(*) * any_value(total_citations), 0) as gini
    from ranked
    group by primary_topic_subfield_id

),

-- Same formula over the cited papers only; ranks recomputed on the subset.
ranked_cited as (

    select
        primary_topic_subfield_id,
        cited_by_count,
        row_number()        over (partition by primary_topic_subfield_id order by cited_by_count) as i,
        count(*)            over (partition by primary_topic_subfield_id)                          as n,
        sum(cited_by_count) over (partition by primary_topic_subfield_id)                          as total_citations
    from cohort
    where cited_by_count > 0

),

cited_only as (

    select
        primary_topic_subfield_id as subfield_id,
        sum((2 * i - n - 1) * cited_by_count)
            / nullif(count(*) * any_value(total_citations), 0) as gini_cited_only
    from ranked_cited
    group by primary_topic_subfield_id

)

select
    headline.subfield_id,
    headline.subfield_display_name,
    headline.is_ai_strict,
    headline.is_ai_broad,
    headline.n_papers,
    headline.total_citations,
    headline.gini,
    cited_only.gini_cited_only  -- NULL for a subfield with no cited papers
from headline
left join cited_only
    on headline.subfield_id = cited_only.subfield_id
