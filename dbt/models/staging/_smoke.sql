-- Throwaway connectivity gate (delete after step 3). Reading one decade from
-- the source exercises the whole fragile path in one shot: oauth + SA
-- impersonation, the external-table read, the storage.objectViewer bucket
-- grant, the write into openalex_analytics_dev, and partition pruning.
select count(*) as n
from {{ source('bronze', 'bronze_external') }}
where publication_year between 1991 and 2000
