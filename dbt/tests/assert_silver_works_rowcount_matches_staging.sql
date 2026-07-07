-- Silver is a projection + classification of staging, never a filter, so its
-- row count must equal stg_works exactly. Returns a row (failing the test) only
-- on a mismatch. Refs both models so it is graph-attached to silver_works.
with counts as (
    select
        (select count(*) from {{ ref('silver_works') }}) as silver_n,
        (select count(*) from {{ ref('stg_works') }})    as staging_n
)
select *
from counts
where silver_n != staging_n
