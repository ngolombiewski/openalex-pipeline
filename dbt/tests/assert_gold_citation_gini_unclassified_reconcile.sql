-- The synthetic subfield bucket exists iff null-subfield papers exist in the
-- built Q3 population, and it can never carry an AI label. Per-cell additive
-- reconciliation is covered by the independent source oracle.
with source_population as (

    select count(*) as n_papers
    from {{ ref('silver_works') }}
    where publication_year between
            {{ var('gini_cohort_min') }}
            and {{ var('gini_citation_year_max') }} - 1
      and primary_topic_subfield_id is null

),

output_population as (

    select
        count(*) as n_rows,
        countif(is_ai_strict or is_ai_broad) as ai_labeled_rows
    from {{ ref('gold_citation_gini_by_subfield') }}
    where subfield_id = '__unclassified__'

)

select source_population.*, output_population.*
from source_population
cross join output_population
where (source_population.n_papers = 0 and output_population.n_rows != 0)
   or (source_population.n_papers > 0 and output_population.n_rows = 0)
   or output_population.ai_labeled_rows > 0
