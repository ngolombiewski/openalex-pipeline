import assert from "node:assert/strict";
import { test } from "node:test";

import { provenance } from "../src/data/provenance.ts";
import { SnapshotDataError } from "../src/data/snapshot.ts";
import { committedSnapshot } from "./fixtures.ts";

function rejects(mutate: (meta: ReturnType<typeof committedSnapshot>["meta"]) => void, message: RegExp): void {
  const { meta } = committedSnapshot();
  mutate(meta);
  assert.throws(
    () => provenance(meta),
    (error: unknown) => error instanceof SnapshotDataError && error.file === "snapshot.json" && message.test(error.message),
  );
}

test("committed provenance renders an unknown revision as not recorded", () => {
  const source = provenance(committedSnapshot().meta);
  assert.equal(source.exportedAt, "1 October 2026, 10:46 UTC");
  assert.equal(source.pipelineRevision, "not recorded");
  assert.equal(source.sourceTables.length, 4);
});

test("a recorded revision is shown as recorded", () => {
  const { meta } = committedSnapshot();
  meta.pipeline_revision = "bb9bff9";
  assert.equal(provenance(meta).pipelineRevision, "bb9bff9");
});

test("exported_at with an offset is not UTC", () => {
  rejects((meta) => (meta.exported_at = "2026-10-01T12:46:52+02:00"), /exported_at .* is not a UTC timestamp/);
});

test("exported_at without a zone is not UTC", () => {
  rejects((meta) => (meta.exported_at = "2026-10-01T10:46:52"), /not a UTC timestamp/);
});

test("source table outside openalex_analytics", () => {
  rejects(
    (meta) => (meta.source_tables.gold_ai_share_by_year = "openalex-pipeline.openalex_dev.gold_ai_share_by_year"),
    /source_tables.gold_ai_share_by_year=.* is not a production openalex_analytics/,
  );
});

test("source table not fully qualified", () => {
  rejects(
    (meta) => (meta.source_tables.gold_citation_age_by_year = "openalex_analytics.gold_citation_age_by_year"),
    /source_tables.gold_citation_age_by_year/,
  );
});

test("source table named after another relation", () => {
  rejects(
    (meta) => (meta.source_tables.gold_citation_gini_by_group = "openalex-pipeline.openalex_analytics.gold_citation_gini_by_subfield"),
    /source_tables.gold_citation_gini_by_group/,
  );
});
