-- Discrete weighted citation-age quantiles must be monotonically ordered.
select
    citation_year,
    cited_group,
    p25_citation_age,
    median_citation_age,
    p75_citation_age
from {{ ref('gold_citation_age_by_year') }}
where p25_citation_age > median_citation_age
   or median_citation_age > p75_citation_age
