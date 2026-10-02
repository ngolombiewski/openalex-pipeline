import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { CITED_GROUPS, SnapshotDataError, selectQ2, type Snapshot } from "../src/data/snapshot.ts";
import { percent } from "../src/format.ts";
import { q2Facts, q2LabelOffsets, q2Points, type Q2Point } from "../src/sections/q2.ts";
import { committedSnapshot } from "./fixtures.ts";

function setMedian(snapshot: Snapshot, year: number, group: string, median: number): void {
  snapshot.citationAge.find((r) => r.citation_year === year && r.cited_group === group)!.median_citation_age = median;
}

function rejects(snapshot: Snapshot, message: RegExp): void {
  assert.throws(
    () => q2Facts(snapshot),
    (error: unknown) => error instanceof SnapshotDataError && /Q2 headline no longer holds/.test(error.message) && message.test(error.message),
  );
}

test("chart points carry exactly the table's rows and medians", () => {
  const view = selectQ2(committedSnapshot());
  assert.deepEqual(
    q2Points(view).map((p) => [p.year, p.group, p.median]),
    view.map((r) => [r.citation_year, r.cited_group, r.median_citation_age]),
  );
  assert.equal(view.length, 14 * CITED_GROUPS.length);
});

describe("end-label offsets", () => {
  const point = (group: Q2Point["group"], median: number): Q2Point => ({ year: 2025, group, median });

  test("three tied groups spread around the shared value", () => {
    assert.deepEqual(q2LabelOffsets([point("ai", 5), point("cv_pr", 5), point("rest_cs", 5)]), { ai: -1, cv_pr: 0, rest_cs: 1 });
  });

  test("distinct values keep their own position", () => {
    assert.deepEqual(q2LabelOffsets([point("ai", 6), point("cv_pr", 5), point("rest_cs", 5)]), { ai: 0, cv_pr: -0.5, rest_cs: 0.5 });
  });
});

describe("numerical claims", () => {
  const facts = q2Facts(committedSnapshot());

  test("medians move from 8 to 5 for AI and 7 to 5 for the others", () => {
    assert.deepEqual([facts.firstYear, facts.lastYear], [2012, 2025]);
    assert.deepEqual(facts.firstMedian, { ai: 8, cv_pr: 7, rest_cs: 7 });
    assert.deepEqual(facts.lastMedian, { ai: 5, cv_pr: 5, rest_cs: 5 });
  });

  test("latest shares aged at most five years", () => {
    assert.equal(percent(facts.lastShareLte5.ai), "55.4%");
    assert.equal(percent(facts.lastShareLte5.cv_pr), "57.2%");
    assert.equal(percent(facts.lastShareLte5.rest_cs), "54.3%");
  });
});

describe("claims the snapshot no longer supports", () => {
  test("a median that did not fall", () => {
    const snapshot = committedSnapshot();
    setMedian(snapshot, 2025, "rest_cs", 7);
    rejects(snapshot, /rest_cs median did not fall/);
  });

  test("AI not the oldest in the first year", () => {
    const snapshot = committedSnapshot();
    setMedian(snapshot, 2012, "cv_pr", 8);
    rejects(snapshot, /AI's 2012 median is not the oldest/);
  });

  test("latest medians differ", () => {
    const snapshot = committedSnapshot();
    setMedian(snapshot, 2025, "ai", 4);
    rejects(snapshot, /2025 medians differ/);
  });
});
