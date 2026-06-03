# ADR 005 — Bronze Uniqueness Check Is Non-Blocking

**Status:** Accepted

## Context

Bronze ingestion checks for duplicate `id` values within each year shard after writing the Parquet file. We needed to decide whether a duplicate should block ingestion or be surfaced as a warning.

## Decision

The uniqueness check is non-blocking. Bronze computes `duplicate_id_count` per year and records it in the manifest. No rows are removed. A year with duplicates ingests successfully; the manifest surfaces the count as a warning for human review.

## Rationale

The cause of a duplicate `id` within a year shard is genuinely ambiguous between two sources:

1. **On-disk corruption** — an extraction defect produced the same record twice.
2. **OpenAlex cursor-pagination churn** — the source index shifted mid-extraction (a work was re-indexed or updated), causing the same work to appear on two different pages. This is a source artifact, not an extraction bug.

Extraction's resume logic overwrites `page-{next_page}` on resume, making resume-path duplication unlikely by construction. This reinforces that a duplicate, if found, more likely reflects source churn than an extraction defect.

A hard failure would wrongly punish a pipeline that correctly extracted what the API returned. The right response to a source churn duplicate is to note it and let downstream deduplication (silver layer) handle it with full context, not to halt bronze.

This mirrors extraction's treatment of `count_mismatch`: surface the signal, never block on it.

## Alternatives considered

**Block on any duplicate:** Fail the year if `duplicate_id_count > 0`. Rejected — punishes source-churn duplicates that are not extraction failures, with no recourse (re-extracting the same year would likely reproduce the duplicate if the source hasn't settled).

**Deduplicate silently in bronze:** Remove duplicates during ingestion, keep the first occurrence. Rejected — bronze is a thin format conversion; deduplication is a semantic decision (which occurrence is canonical?) that belongs in silver where it can be tested and audited. Silent deduplication in bronze would make the row count diverge from extraction's `records_fetched` with no explanation.

**Skip the check entirely:** Don't count duplicates at all. Rejected — the check costs little and surfaces a signal that would otherwise be invisible until analysis produces unexpected results.
