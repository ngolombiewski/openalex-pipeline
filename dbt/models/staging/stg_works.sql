{{
  config(
    materialized='table',
    partition_by={
      'field': 'publication_year',
      'data_type': 'int64',
      'range': {'start': 1950, 'end': 2027, 'interval': 1},
    },
    cluster_by=['primary_topic_subfield_id'],
  )
}}

-- Staging over the bronze works external table. Does exactly four things and
-- nothing else: parse the eight JSON-string columns, type the two date columns,
-- apply the corpus-hygiene filters, and deduplicate on `id`. No classification
-- (that is silver), no aggregation (that is gold). See docs/staging-design.md §4.

with source as (

    select *
    from {{ source('bronze', 'bronze_external') }}
    -- Quality filters + corpus-bounds guard, combined into one WHERE. Both
    -- bounds always render (the prod defaults are the true corpus bounds), and
    -- the year predicate is what prunes partitions at the external read. The
    -- QUALIFY dedup below runs on the survivors of this filter.
    --
    -- NULL handling is intentional, not incidental: `= false` excludes rows
    -- where is_retracted is NULL (NULL = false -> NULL -> dropped), not only the
    -- explicitly-TRUE rows. At full corpus that is 1,282 works (~0.009%) whose
    -- retraction status is simply unrecorded; we drop them conservatively rather
    -- than infer "not retracted". is_paratext has no NULLs. Verified at the
    -- step-6 prod run; reconciliation in STATE.md accounts for these 1,282.
    where is_retracted = false
      and is_paratext = false
      and publication_year between {{ var('year_min') }} and {{ var('year_max') }}

),

parsed as (

    select
        -- identity + scalars, carried verbatim
        id,
        title,
        publication_year,
        type,
        language,
        is_retracted,
        is_paratext,
        cited_by_count,
        fwci,
        referenced_works_count,
        doi,

        -- dates: typed here, deferred from bronze by design. SAFE.* so a
        -- malformed value yields NULL rather than failing the whole model; the
        -- singular tests assert that the non-null parse-failure count is ~0.
        safe.parse_date('%Y-%m-%d', publication_date)                       as publication_date,
        safe.parse_timestamp('%Y-%m-%dT%H:%M:%E*S', updated_date)           as updated_date,

        -- primary_topic — flattened. subfield/field drive classification (silver).
        json_value(primary_topic, '$.id')                                   as primary_topic_id,
        json_value(primary_topic, '$.display_name')                         as primary_topic_display_name,
        safe_cast(json_value(primary_topic, '$.score') as float64)          as primary_topic_score,
        json_value(primary_topic, '$.subfield.id')                          as primary_topic_subfield_id,
        json_value(primary_topic, '$.subfield.display_name')                as primary_topic_subfield_display_name,
        json_value(primary_topic, '$.field.id')                             as primary_topic_field_id,
        json_value(primary_topic, '$.field.display_name')                   as primary_topic_field_display_name,

        -- open_access — the two signal fields
        safe_cast(json_value(open_access, '$.is_oa') as bool)               as is_oa,
        json_value(open_access, '$.oa_status')                              as oa_status,

        -- cited_by_percentile_year — min/max
        safe_cast(json_value(cited_by_percentile_year, '$.min') as int64)   as cited_by_percentile_year_min,
        safe_cast(json_value(cited_by_percentile_year, '$.max') as int64)   as cited_by_percentile_year_max,

        -- citation_normalized_percentile — value + top-N flags
        safe_cast(json_value(citation_normalized_percentile, '$.value') as float64)              as citation_normalized_percentile_value,
        safe_cast(json_value(citation_normalized_percentile, '$.is_in_top_1_percent') as bool)   as is_in_top_1_percent,
        safe_cast(json_value(citation_normalized_percentile, '$.is_in_top_10_percent') as bool)  as is_in_top_10_percent,

        -- ids — external crosswalk. Absent keys yield NULL (intended, not repaired).
        json_value(ids, '$.openalex')                                       as openalex_id,
        json_value(ids, '$.doi')                                            as doi_url,
        json_value(ids, '$.mag')                                            as mag_id,
        json_value(ids, '$.pmid')                                           as pmid,
        json_value(ids, '$.pmcid')                                          as pmcid,

        -- counts_by_year — typed nested array, critical for half-life (Q2).
        -- Kept nested, not pre-aggregated. Empty/[] (zero-citation works, ~61%
        -- of the corpus) yields an empty array, not an error.
        array(
            select as struct
                safe_cast(json_value(e, '$.year') as int64)           as year,
                safe_cast(json_value(e, '$.cited_by_count') as int64) as cited_by_count
            from unnest(json_query_array(counts_by_year, '$')) as e
        )                                                                   as counts_by_year,

        -- topics — full typed array; retained, not used for classification.
        array(
            select as struct
                json_value(e, '$.id')                                 as id,
                json_value(e, '$.display_name')                       as display_name,
                safe_cast(json_value(e, '$.score') as float64)        as score,
                json_value(e, '$.subfield.id')                        as subfield_id,
                json_value(e, '$.subfield.display_name')              as subfield_display_name,
                json_value(e, '$.field.id')                           as field_id,
                json_value(e, '$.field.display_name')                 as field_display_name
            from unnest(json_query_array(topics, '$')) as e
        )                                                                   as topics,

        -- keywords — typed array; low signal, light parse.
        array(
            select as struct
                json_value(e, '$.id')                                 as id,
                json_value(e, '$.display_name')                       as display_name,
                safe_cast(json_value(e, '$.score') as float64)        as score
            from unnest(json_query_array(keywords, '$')) as e
        )                                                                   as keywords

    from source

),

deduped as (

    -- Dedup deferred from bronze (>=1 known duplicate id, most likely a stale
    -- cursor re-emitting a page). Keep the freshest OpenAlex snapshot. `nulls
    -- last` guards the edge where a malformed updated_date parsed to NULL — a
    -- real timestamp always wins over a null one. Exact ties are byte-identical
    -- re-emits, so an arbitrary pick is fine.
    select *
    from parsed
    qualify row_number() over (
        partition by id
        order by updated_date desc nulls last
    ) = 1

)

select * from deduped
