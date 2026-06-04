# TODO

## Bronze Ingestion — deferred follow-ups

The bronze module is implemented and green; these are out-of-scope-for-now
items that surfaced during it.

- **Migrate extraction to `OPENALEX_DATA_ROOT`.** Extraction still reads
  `OPENALEX_DATA_DIR` (`extraction/settings.py`). Bronze already derives its
  dirs from the shared `OPENALEX_DATA_ROOT` (`{root}/extract`, `{root}/bronze`).
  Point extraction at `{OPENALEX_DATA_ROOT}/extract` once the extraction module
  review is ready.
- **Bronze landing layout for GCS/BigQuery.** Confirm whether the cloud lift
  wants Hive-style partition directories
  (`.../publication_year={year}/{year}.parquet`) for BigQuery external-table
  partition pruning, vs. the current flat `{year}.parquet`. (Also tracked under
  *Infrastructure* in `docs/plan.md`; decide when wiring the warehouse load.)
