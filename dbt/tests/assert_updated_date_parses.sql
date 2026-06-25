-- A non-null source updated_date that fails SAFE.PARSE_TIMESTAMP is a contract
-- breach (OpenAlex emits ISO-8601 with microseconds). Test passes on zero rows.
-- Reads the source directly (staging keeps only the parsed TIMESTAMP); bounded
-- by the corpus vars so it prunes on the dev slice.
select id
from {{ source('bronze', 'bronze_external') }}
where publication_year between {{ var('year_min') }} and {{ var('year_max') }}
  and updated_date is not null
  and safe.parse_timestamp('%Y-%m-%dT%H:%M:%E*S', updated_date) is null
