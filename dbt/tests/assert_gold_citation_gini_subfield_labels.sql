-- A deterministic max label is only a fallback mechanism: conflicting source
-- labels are corruption, and every published real subfield has one stable
-- non-null label across its complete built series.
with source_conflicts as (

    select
        primary_topic_subfield_id as subfield_id,
        count(distinct primary_topic_subfield_display_name) as n_labels
    from {{ ref('silver_works') }}
    where publication_year between
            {{ var('gini_cohort_min') }}
            and {{ var('gini_citation_year_max') }} - 1
      and primary_topic_subfield_id is not null
      and primary_topic_subfield_display_name is not null
    group by primary_topic_subfield_id
    having count(distinct primary_topic_subfield_display_name) > 1

),

output_conflicts as (

    select
        subfield_id,
        count(distinct subfield_display_name) as n_labels
    from {{ ref('gold_citation_gini_by_subfield') }}
    where subfield_id != '__unclassified__'
    group by subfield_id
    having count(distinct subfield_display_name) != 1

)

select 'source' as location, subfield_id, n_labels
from source_conflicts
union all
select 'output', subfield_id, n_labels
from output_conflicts
