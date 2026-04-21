# OpenAlex Bulk Metadata Downloader — Spec

## Context

The `openalex-official` CLI was evaluated as the data extraction tool for this pipeline but was discarded due to bugs and an immature codebase. We implement our own thin API wrapper instead.

## New File

**`scripts/openalex_downloader.py`**

No other files are created or modified.

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| HTTP | `requests.Session` | Already in deps; synchronous is sufficient |
| JSON serialization | `orjson` | Already in deps; 3–5× faster than stdlib `json` |
| Logging | `loguru` | Already in deps; writes to stderr + rotating log file |
| Config / API key | `pydantic-settings` → `OPENALEX_API_KEY` env var | Already in deps; consistent with rest of pipeline |
| Output format | JSONL, one file per API page (200 records) | Finest resume granularity; natural unit of work |
| Output layout | Flat: all batch files in `output_dir/` | Per-year invocation makes subdirs redundant |
| Checkpoint | `.checkpoint.json` in output dir, atomic rename | Simple and robust |
| Writes | Atomic: write to `.tmp`, then rename to final path | No partial files on crash |
| Column filtering | Applied at write time from `SELECTED_FIELDS` list | Keeps JSONL lean; matches bronze layer schema |

## Module Structure

```python
SELECTED_FIELDS: list[str]              # columns to retain from each Work record (see DATA_MODEL.md)

class Settings(BaseSettings):           # reads OPENALEX_API_KEY from env

@dataclass
class Checkpoint:                       # persisted state: filter_str, cursor, batch_index, counts

class OpenAlexDownloader:
    __init__(output_dir, filter_str, api_key)
    run()                               # main entry point: pre-run check, then paginate
    _preflight(filter_str)              # health check + record count + threshold warning
    _load_checkpoint() -> Checkpoint | None
    _save_checkpoint(...)               # atomic write
    _fetch_page(cursor) -> (records, next_cursor)   # retry logic lives here
    _write_batch(records, batch_index)  # column filter + atomic write
    _batch_path(batch_index) -> Path    # flat: output_dir/batch_NNNNNN.jsonl

if __name__ == "__main__":             # argparse CLI for standalone use
```

## Key Behaviors

### Pre-run check (`_preflight`)
Before starting (or resuming) a download:
1. Hit `GET /works?filter={filter_str}&per-page=1` and verify HTTP 200 — confirms key is valid and filter is accepted
2. Log `meta.count` as expected record count
3. If `meta.count > 2_000_000`: log a warning suggesting a narrower filter (e.g. add `publication_year`)
4. If resuming: log records already completed from checkpoint

### Resume logic
- On startup: look for `.checkpoint.json` in output dir
- If found and `filter_str` matches: resume from saved `cursor` + `batch_index`
- If filter mismatch: log error and exit — never silently overwrite a different dataset
- If not found: start fresh (`cursor="*"`, `batch_index=0`)

### 429 handling
- Read `Retry-After` header (default 60s), sleep, retry — never fail silently
- If `X-RateLimit-Remaining < X-RateLimit-Credits-Required`: save checkpoint, raise `RuntimeError` with clear message

### 5xx handling
- Exponential backoff: 3 attempts at 5s, 10s, 20s, then raise

### Graceful shutdown (SIGINT / SIGTERM)
- Set `_shutdown` flag on signal; finish writing and checkpointing the current page, then exit cleanly

### Validation
- Skip any record missing the `"id"` field; log count of skipped records per batch

### Column filtering
- Each record is filtered to `SELECTED_FIELDS` before writing
- `SELECTED_FIELDS` matches the bronze layer column list in `DATA_MODEL.md`
- Unknown fields are silently dropped; missing fields are omitted (no error)

### Progress logging
- Pre-run: `expected records: {meta.count}`
- After each batch: `batch {N} | {M} records | {R} rec/s | cursor: {cursor}`
- Log written to stderr and `{output_dir}/download.log` (loguru, rotation at 100 MB)

## Fetch Logic

```
GET https://api.openalex.org/works
    ?filter={filter_str}
    &cursor={cursor}
    &per-page=200
    &api_key={api_key}
```

One request per page. The Work JSON returned by the list endpoint is written directly to JSONL — no secondary singleton fetch.

## Standalone CLI

```bash
uv run scripts/openalex_downloader.py \
  --filter "primary_topic.id:T10320,publication_year:2020" \
  --output ./data/raw/test
```

Intended invocation: one run per publication year, each with its own output directory and checkpoint.

## Output Layout

```
data/raw/
  2024/
    .checkpoint.json
    download.log
    batch_000000.jsonl    # 200 records (one API page)
    batch_000001.jsonl
    ...
  2023/
    .checkpoint.json
    download.log
    batch_000000.jsonl
    ...
```

## Verification

1. Run with `--filter "primary_topic.id:T10320,publication_year:2020"` against a small slice
2. Confirm pre-run check logs expected record count
3. Confirm JSONL files appear flat in output dir with correct naming
4. Kill mid-run with Ctrl-C → verify `.checkpoint.json` exists and last batch file is complete
5. Re-run → confirm resume from saved cursor without rewriting existing batch files
6. Exhaust rate limit → confirm 429 triggers sleep+retry; credits exhausted triggers clean exit with checkpoint saved
7. Spot-check a record: `head -1 data/raw/2024/batch_000000.jsonl | python -m json.tool` → valid JSON with `"id"` field and only selected columns present