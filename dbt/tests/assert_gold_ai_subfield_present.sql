-- The AI subfield (the pinned subfield_ai var) must appear in both
-- subfield-grain gold tables — its absence means the aggregation silently
-- lost the one subfield the whole analysis is about. Returns the table names
-- it is missing from.
select 'gold_citation_half_life_by_subfield' as missing_from
from (select 1)
where '{{ var("subfield_ai") }}' not in (
    select subfield_id from {{ ref('gold_citation_half_life_by_subfield') }}
)

union all

select 'gold_citation_gini_by_subfield' as missing_from
from (select 1)
where '{{ var("subfield_ai") }}' not in (
    select subfield_id from {{ ref('gold_citation_gini_by_subfield') }}
)
