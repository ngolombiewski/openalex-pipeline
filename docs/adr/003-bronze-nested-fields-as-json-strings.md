# ADR 003 — Bronze Nested Fields Landed as JSON Strings

**Status:** Accepted

## Context

The bronze works table includes eight nested fields from the OpenAlex API response: `primary_topic`, `topics`, `counts_by_year`, `cited_by_percentile_year`, `citation_normalized_percentile`, `open_access`, `ids`, and `keywords`. These are JSON objects or arrays in the source JSONL. We needed to decide how to represent them in the Parquet output.

Polars parses these fields into Struct/List types when reading JSONL regardless of the requested output dtype. The question was whether to keep them as typed Polars structures or re-encode them to JSON strings.

## Decision

All eight nested fields are re-encoded to JSON strings (`String` dtype) in the Parquet output. Flattening and typed parsing happen downstream in dbt staging models.

## Rationale

The primary motivation is schema stability across years. OpenAlex's nested struct shapes can shift across years as the API evolves — new subfields added, field types changed, optional keys appearing or disappearing. If Parquet files for different years carry different Struct schemas, downstream tooling must negotiate the union schema or fail. A `String` column has an identical, trivially stable type regardless of what the JSON inside looks like.

This is not about avoiding parsing work: Polars parses the JSON regardless (into Struct/List). The re-encode step adds CPU cost but buys a stable, uniform schema across all 75 year-shards.

Flattening to typed columns in dbt is the right layer: dbt staging models can handle OpenAlex schema quirks in one place, with explicit column extraction, rather than implicitly through Polars Struct inference.

## Alternatives considered

**Land nested fields as Polars Struct/List:** Avoids the re-encode step. Rejected — creates schema fragility across years. A new optional key in `primary_topic` in 2023 would produce a different Parquet schema than 2010, requiring union-schema handling in every downstream reader.

**Flatten nested fields to scalar columns in bronze:** Extract `primary_topic.subfield.id`, `primary_topic.field.id`, etc. as top-level columns during ingestion. Rejected — bronze is a thin format conversion; flattening is a semantic transformation that belongs in dbt where it can be tested and evolved independently.
