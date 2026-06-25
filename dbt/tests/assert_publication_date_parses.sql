-- A non-null source publication_date that fails SAFE.PARSE_DATE is a contract
-- breach (OpenAlex should always emit YYYY-MM-DD). Test passes on zero rows.
-- Reads the source directly because staging keeps only the parsed DATE, so the
-- raw string is unavailable downstream; bounded by the corpus vars so it prunes
-- on the dev slice.
select id
from {{ source('bronze', 'bronze_external') }}
where publication_year between {{ var('year_min') }} and {{ var('year_max') }}
  and publication_date is not null
  and safe.parse_date('%Y-%m-%d', publication_date) is null
