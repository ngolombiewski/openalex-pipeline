# Extraction Module Report

Status snapshot from the raw extraction data in `data/extract`.

Checked at: 2026-05-23 08:33 Europe/Berlin

## Summary

The extraction module is behaving correctly so far. Completed years are
continuous from 1950 through 2004, and the current stopped year, 2005, is in a
clean resumable state after the OpenAlex daily credit limit was reached.

No storage integrity issues were found. The only notable data pattern is a large
record-count jump from 2001 to 2002, which was verified against the OpenAlex API
`meta.count` and appears to be source-data behavior rather than an extraction
problem.

## Current State

| Item | Value |
|---|---:|
| Year directories present | 1950-2005 |
| Completed year reports | 1950-2004 |
| Completed records | 2,844,840 |
| In-progress year | 2005 |
| 2005 records written | 10,800 |
| Total JSONL records present | 2,855,640 |
| `data/extract` size | 9.2G |

## Integrity Checks

- Completed years are continuous from 1950 through 2004.
- All completed years have `count_mismatch=false`.
- Completed report counts match actual JSONL line counts.
- Completed report page counts match actual page-file counts.
- Page numbering is contiguous.
- Non-final completed pages contain at most 200 records.
- Sampled records from 1950, 2004, and 2005 had the expected selected columns.
- Sampled records had `publication_year` matching their shard directory.
- Sampled records had `primary_topic.field.id = https://openalex.org/fields/17`.

## Stopped State

The daily credit limit stopped the run during 2005:

```text
year 2005 page 54 written: records=200 next_cursor=True
daily limit reached while processing year 2005
status: stopped_daily_limit
stopped at year: 2005
```

On disk, this corresponds to:

- `data/extract/2005/_META.json` present.
- `data/extract/2005/_CURSOR.json` present.
- `data/extract/2005/_YEAR_REPORT.json` absent.
- `data/extract/2005/page-0001.jsonl` through `page-0054.jsonl` present.
- `_CURSOR.json` points to `next_page=55`.
- `54 * 200 = 10,800` records written.

This is the expected resumable state. The next run should continue at 2005 page
55.

## Notable Data Pattern

There is a large year-over-year count jump in 2002:

| Year | Records |
|---:|---:|
| 2000 | 142,719 |
| 2001 | 154,437 |
| 2002 | 294,367 |
| 2003 | 259,088 |
| 2004 | 270,147 |

The 2001 to 2002 increase is 139,930 records, about 90.6%. This matches the
OpenAlex API `meta.count` for the same filter, so it should be investigated in
analysis/visualization rather than treated as an extraction failure.

## Deferred Checks

A full-row null-rate/filter scan was deferred because it was slow over the
current JSONL volume. Report-level integrity and bounded record samples were
clean. A broader profile pass should be part of the bronze ingestion work.
