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

-- Silver: AI classification + projection to the analytical grain. One row per
-- work, same grain as staging (no filter, no aggregation — trust the layer
-- below). Adds the ai_strict/ai_broad ablation flags and carries forward only
-- the columns Q1–Q3 need. See docs/design-archive/silver-design.md.

select
    -- identity + dimensions
    id,
    publication_year,
    publication_date,
    primary_topic_id,
    primary_topic_display_name,
    primary_topic_subfield_id,
    primary_topic_subfield_display_name,

    -- AI classification (DATA_MODEL.md). Match on the stable subfield id, pinned
    -- as vars. coalesce keeps the flags strictly boolean: a NULL subfield (none
    -- in the corpus today, but the staging not_null test is soft) is non-AI, not
    -- NULL, and stays in the CS denominator.
    coalesce(primary_topic_subfield_id = '{{ var("subfield_ai") }}', false)     as is_ai_strict,
    coalesce(primary_topic_subfield_id in ('{{ var("subfield_ai") }}',
                                           '{{ var("subfield_cv_pr") }}'), false) as is_ai_broad,

    -- measures for the analytical questions
    cited_by_count,     -- Q3 (Gini on citation impact)
    fwci,               -- Q3 alternative impact measure
    counts_by_year      -- Q2 (half-life); kept nested, reshaped in gold

from {{ ref('stg_works') }}
