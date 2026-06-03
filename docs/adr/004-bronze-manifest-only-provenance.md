# ADR 004 — Bronze Provenance Lives in the Manifest, Not in Row Columns

**Status:** Accepted

## Context

Bronze ingestion adds metadata about when and how data was ingested. We needed to decide where this provenance lives: as additional columns on each row in the Parquet file, or in a separate manifest file at year granularity.

An earlier sketch of the design included per-row columns `_ingested_at` and `_source_file` (the page-file that contained each record).

## Decision

Bronze adds zero columns to the records. All provenance — ingest timestamp, source path, record counts, extraction metadata — lives in a single `manifest.csv` at year granularity. The manifest has one row per year and is rebuilt wholesale on every run.

## Rationale

Per-row `_ingested_at` would produce ~14.7M identical-within-a-year timestamps. This is pure storage waste with no analytical value: the timestamp is a property of the year-shard, not of the individual work.

Per-row `_source_file` (page-file traceability) is not needed by any of the three analytical questions. Adding it speculatively violates the principle of not designing for hypothetical future requirements.

Year-granularity provenance in the manifest is sufficient for operational needs: verifying extraction→bronze record counts, tracking ingest timestamps, forwarding extraction's `count_mismatch` signal. The manifest is human-readable, tiny (~75 rows for 1950–2024), and trivially rebuilt.

## Alternatives considered

**Per-row `_ingested_at`:** Timestamp column on every record. Rejected — 14.7M identical values per year; no analytical use; wastes storage.

**Per-row `_source_file`:** Page-file path on every record for full traceability. Rejected — no analytical question requires it; adds storage cost for a debugging capability that can be approximated from the manifest and extraction state files.

**Separate provenance Parquet alongside each year shard:** Store provenance as a sidecar file per year. Rejected — adds complexity over a single manifest CSV for no benefit at this scale.
