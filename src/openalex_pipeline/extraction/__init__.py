"""OpenAlex works extraction module.

Bronze-layer ingest: fetches CS works from the OpenAlex API and lands them
as raw JSONL page files on local disk. Idempotent and resumable across
invocations. See docs/extraction-design.md for the full design.

Public entry point: `openalex_pipeline.extraction.runner.run` or
`python -m openalex_pipeline.extraction`.
"""
