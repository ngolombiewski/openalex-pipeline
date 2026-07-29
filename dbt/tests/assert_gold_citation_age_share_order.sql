-- Inclusive recent-citation windows are nested and their shares must be
-- monotonically non-decreasing.
select
    citation_year,
    cited_group,
    share_age_lte_2,
    share_age_lte_5,
    share_age_lte_10
from {{ ref('gold_citation_age_by_year') }}
where share_age_lte_2 > share_age_lte_5
   or share_age_lte_5 > share_age_lte_10
