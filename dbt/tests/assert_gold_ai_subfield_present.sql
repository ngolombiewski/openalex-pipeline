-- The AI subfield (the pinned subfield_ai var) must appear in Q3's
-- subfield-grain gold table. Its absence means the aggregation silently lost
-- the one subfield the analysis is about.
select 'gold_citation_gini_by_subfield' as missing_from
from (select 1)
where '{{ var("subfield_ai") }}' not in (
    select subfield_id from {{ ref('gold_citation_gini_by_subfield') }}
)
