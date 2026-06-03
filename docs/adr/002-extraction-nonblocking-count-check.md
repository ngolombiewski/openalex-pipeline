# ADR 002 — Extraction Count Check Is Non-Blocking

**Status:** Accepted

## Context

The OpenAlex API returns a `meta.count` on the first page of any paginated query. This is the API's estimate of total matching records. After paginating a full year, we know the actual number of records fetched. The question was whether a mismatch between these two numbers should block year completion.

## Decision

A count mismatch is recorded in `_YEAR_REPORT.json` as `count_mismatch: true` but never blocks completion. The runner surfaces it as a warning in the run report. A mismatched year is ingested normally by the bronze layer, which forwards the flag into its manifest.

## Rationale

The `meta.count` field is a snapshot from the first page fetch. OpenAlex's underlying index can shift during a multi-hour extraction run: records added, removed, or re-indexed between the first page and the last. A net count change does not mean the data is wrong — it means the source moved while we were reading it.

The check is a smoke alarm: it catches gross extraction failures (e.g. pages skipped, cursor loop bug) while acknowledging it cannot detect churn (a concurrent add and delete leaves the count matching while the data has changed). The real defense against drift is that a year usually completes within a single day, keeping the drift window small.

Blocking on mismatch would create false failures for a working pipeline operating against a live source, with no practical recourse (we cannot re-extract a year mid-day).

## Alternatives considered

**Block on mismatch:** Treat any count difference as a hard failure requiring re-extraction. Rejected — produces false failures from normal source churn and provides no recourse within the daily credit budget.

**Skip the check entirely:** Don't compare counts at all. Rejected — the check catches real extraction bugs (cursor loop errors, truncated runs) at essentially zero cost. Surfacing a warning is better than silent divergence.
