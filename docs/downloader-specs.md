# OpenAlex Bulk Metadata Downloader — Spec

## Context

The `openalex-official` CLI was evaluated as the data extraction tool for this pipeline but has two disqualifying issues:

1. **Silent failure on 429**: failed records are marked as completed in the checkpoint, so rate-limited works are silently skipped on resume.
2. **Redundant singleton API calls**: the CLI fetches the full work list via paginated cursor queries, then makes an additional `GET /works/{id}` call for every single record — doubling all API requests for no benefit, since the list endpoint already returns complete Work objects.

The CLI's async worker pool provides zero benefit for sequential cursor pagination (each page depends on the previous cursor). A minimal, owned replacement is simpler, faster, and fully transparent.

This module is the first piece of source code in `openalex-pipeline`. It is intentionally standalone (no Dagster dependency) so it can be tested and run directly during development, then wrapped in a Dagster asset when the pipeline is wired up.

## New File

**`src/ingest/openalex_downloader.py`** (~180 lines)

No other files are created or modified.

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| HTTP | `requests.Session` | Already in deps; synchronous is sufficient for sequential pagination |
| JSON serialization | `orjson` | Already in deps; 3–5× faster than stdlib `json` |
| Logging | `loguru` | Already in deps; writes to stderr + rotating log file |
| Config / API key | `pydantic-settings` → `OPENALEX_API_KEY` env var | Already in deps; consistent with rest of pipeline |
| Output format | JSONL, one file per API page (200 records) | Finest resume granularity; natural unit of work |
| Checkpoint | `.checkpoint.json` in output dir, atomic rename | Simple and robust |
| Nesting | `{output}/NNN/batch_NNNNNN.jsonl` where `NNN = batch_index // 200` | ~200 files per dir; ~368 dirs for full CS dataset |
| Writes | Atomic: write to `.tmp`, then rename to final path | No partial files on crash |

## Module Structure

```python
class Settings(BaseSettings):           # reads OPENALEX_API_KEY from env

@dataclass
class Checkpoint:                        # persisted state (filter, cursor, batch_index, counts)

class OpenAlexDownloader:
    __init__(output_dir, filter_str, api_key)
    run()                                # main entry point
    _load_checkpoint() -> Checkpoint | None
    _save_checkpoint(...)                # atomic write
    _fetch_page(cursor) -> (records, next_cursor)  # retry logic lives here
    _write_batch(records, batch_index)   # atomic write
    _batch_path(batch_index) -> Path     # nesting logic

if __name__ == "__main__":              # argparse CLI for standalone use
```

## Key Behaviors

### Resume logic
- On startup: look for `.checkpoint.json` in output dir
- If found and filter matches: resume from saved `cursor` + `batch_index`
- If filter mismatch: warn and exit (never silently overwrite a different dataset)
- If not found: start fresh (`cursor="*"`, `batch_index=0`)

### 429 handling
- Read `Retry-After` header (default 60s), sleep, retry — never fail silently
- If `X-RateLimit-Remaining < X-RateLimit-Credits-Required`: raise `RuntimeError` with a clear message; checkpoint is saved before exit

### 5xx handling
- Exponential backoff: 3 attempts at 5s, 10s, 20s, then raise

### Graceful shutdown (SIGINT / SIGTERM)
- Set `_shutdown` flag on signal; finish writing and checkpointing the current page, then exit cleanly

### Validation
- Skip any record missing the `"id"` field; log the count of skipped records per batch

### Progress logging
- After each batch: `batch N | M records | R rec/s`
- Log written to stderr and `{output_dir}/download.log` (loguru rotation at 100 MB)

## Fetch Logic

```
GET https://api.openalex.org/works
    ?filter={filter_str}
    &cursor={cursor}
    &per-page=200
    &api_key={api_key}
```

One request per page. The complete Work JSON returned by the list endpoint is written directly to JSONL — no secondary singleton fetch.

## Standalone CLI Usage

```bash
OPENALEX_API_KEY=your_key python -m src.ingest.openalex_downloader \
  --filter "primary_topic.field.id:17" \
  --output ./data/raw/works
```

## Output Layout

```
data/raw/works/
  .checkpoint.json
  download.log
  000/
    batch_000000.jsonl   # 200 records (one API page)
    batch_000001.jsonl
    ...
    batch_000199.jsonl
  001/
    batch_000200.jsonl
    ...
  367/
    batch_073499.jsonl   # last batch for ~14.7M CS works
```

## Verification

1. Run with `--filter "primary_topic.field.id:17,publication_year:2024"` to test against a small slice
2. Confirm JSONL files appear under nested dirs with correct naming
3. Kill mid-run with Ctrl-C → verify `.checkpoint.json` exists and the last batch file is complete (not truncated)
4. Re-run → confirm it resumes from the saved cursor without rewriting existing batch files
5. Exhaust rate limit → confirm warning is logged and process retries (429) or exits cleanly (credits exhausted) with checkpoint preserved
6. Spot-check a record: `head -1 data/000/batch_000000.jsonl | python -m json.tool` → valid JSON with `"id"` field present
