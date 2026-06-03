# TODO

## Bronze Ingestion

- Decide the bronze nested-field contract after the Polars spike:
  - keep nested fields as Parquet structs/lists if schema inference is stable enough;
  - otherwise encode nested fields as JSON strings as a schema-stability hedge.
- Update `docs/DATA_MODEL.md` if bronze stores nested OpenAlex payloads as JSON strings rather than native nested Parquet fields.
- Remove the stale `_extracted_at` note from `docs/ingestion-design.md`; provenance belongs in the manifest.
- Decide the bronze output layout before implementation:
  - current sketch: one file per year;
  - likely scalable layout: year subdirectories, allowing multiple Parquet files for large years.
- Pin the bronze row-count check behavior:
  - `bronze_row_count` must be compared with extraction `records_fetched`;
  - mismatches should be surfaced clearly in the manifest/reporting.
- Keep duplicate/non-null ID findings as non-blocking data-quality signals, not loud extraction/ingestion failures.
- Use `OPENALEX_DATA_ROOT` as the shared pipeline root going forward, with stage-local suffixes such as `extract` and `bronze`.
- Add `OPENALEX_DATA_ROOT=/home/nils/workspace/openalex-pipeline/data` to `.env`.
- Later, update extraction config to derive its extract directory from `OPENALEX_DATA_ROOT` once the extraction module review is ready.
- Clarify ingestion year-range semantics:
  - env vars define the normal production range;
  - CLI overrides are only for development runs.
- Confirm whether BigQuery/GCS strongly favors Hive-style partition directories for the bronze landing layout.

