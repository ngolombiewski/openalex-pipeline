-- The ablation subset relation (ai_strict ⊆ ai_broad, asserted in silver) must
-- survive aggregation: for every year, strict share <= broad share. Returns
-- the violating years.
select
    strict_rows.publication_year,
    strict_rows.share as strict_share,
    broad_rows.share  as broad_share
from {{ ref('gold_ai_share_by_year') }} as strict_rows
join {{ ref('gold_ai_share_by_year') }} as broad_rows
    on strict_rows.publication_year = broad_rows.publication_year
where strict_rows.variant = 'strict'
  and broad_rows.variant = 'broad'
  and strict_rows.share > broad_rows.share
