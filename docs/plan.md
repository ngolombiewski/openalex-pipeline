# Plan — Open Questions & Prospective Work

This file collects unresolved questions and items that are not yet part of the project state. Remove an item once it is resolved and reflected in `docs/architecture.md` or an ADR.

---

## Open Questions

### Data / Analysis

- **OpenAlex subfield IDs for AI** — The classification rule uses display names (`Artificial Intelligence`, `Computer Vision and Pattern Recognition`). The exact numeric subfield IDs need to be pinned via the API before the dbt staging models can filter on them reliably.
- **Citation half-life methodology** — Cohort-based approximation is the intended approach, but the exact assumptions need to be documented before implementation. The approximation relies on `counts_by_year`; document what "half-life" means in this context.

### Infrastructure

- **External vs. native BigQuery tables** — Try external tables (Parquet on GCS) first. Decide whether to switch to native BigQuery tables based on query performance and cost.
- **`dagster-dbt` integration** — Native `dagster-dbt` integration vs. shelling out to dbt. Decide when wiring Dagster orchestration.

---

## Bronze Ingestion — To Confirm at Smoke-Test

Resolve these once the ingestion function bodies stand and can be run against real page files:

1. **Schema uniformity across years** — Pull one page file per year and inspect whether inferred nested-struct shapes diverge across years. If divergence is real, the JSON-string re-encode (ADR 003) is load-bearing; if not, it is purely for contract stability.
2. **`scan_ndjson` forced-schema behavior** — Confirm how a forced schema interacts with nested fields, and that `.struct.json_encode()` round-trips faithfully.
3. **Zero-byte page file** — Confirm Polars yields an empty frame (not an error) for a zero-byte input file, so the empty-Parquet path holds for zero-result years.
4. **Lazy vs. eager** — Confirm `scan_ndjson` → `sink_parquet` keeps memory bounded on the largest years (~1.5M records). Choose lazy vs. eager based on the result.
5. **Skip rule granularity** — Skip a year on Parquet presence alone, or compare mtime against the source `_YEAR_REPORT.json` to catch a re-extracted year?
6. **Final manifest column set** — Confirm the provisional columns in `ingestion-design.md` once the smoke-test pass is complete.
