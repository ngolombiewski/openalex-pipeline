import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { Q1_FIRST_YEAR, SnapshotDataError, selectQ1, type Snapshot } from "../src/data/snapshot.ts";
import { percent } from "../src/format.ts";
import { q1Facts, q1Points, q1Segments } from "../src/sections/q1.ts";
import { committedSnapshot } from "./fixtures.ts";

function setShare(snapshot: Snapshot, year: number, variant: string, share: number): void {
  snapshot.aiShare.find((r) => r.publication_year === year && r.variant === variant)!.share = share;
}

function rejects(snapshot: Snapshot, message: RegExp): void {
  assert.throws(
    () => q1Facts(snapshot),
    (error: unknown) => error instanceof SnapshotDataError && /Q1 headline no longer holds/.test(error.message) && message.test(error.message),
  );
}

describe("chart and table agreement", () => {
  test("points carry exactly the Q1 view's rows and values", () => {
    const snapshot = committedSnapshot();
    const view = selectQ1(snapshot);
    const points = q1Points(snapshot);
    assert.deepEqual(
      points.map((p) => [p.year, p.variant, p.share, p.aiWorks, p.csWorks, p.partial]),
      view.map((r) => [r.publication_year, r.variant, r.share, r.ai_works, r.cs_works, r.is_partial_year]),
    );
  });

  test("drawn segments cover every point exactly once besides the shared join", () => {
    const points = q1Points(committedSnapshot());
    for (const variant of ["strict", "broad"] as const) {
      const { solid, dashed } = q1Segments(points, variant);
      const series = points.filter((p) => p.variant === variant);
      assert.deepEqual([...solid, ...dashed.slice(1)], series);
    }
  });
});

describe("partial-year rendering", () => {
  test("the dashed segment joins the last complete year to the partial year", () => {
    const points = q1Points(committedSnapshot());
    for (const variant of ["strict", "broad"] as const) {
      const { solid, dashed } = q1Segments(points, variant);
      assert.deepEqual(dashed.map((p) => [p.year, p.partial]), [[2025, false], [2026, true]]);
      assert.ok(solid.every((p) => !p.partial));
      assert.equal(solid[0]?.year, Q1_FIRST_YEAR);
    }
  });

  test("no partial year draws no dashed segment", () => {
    const points = q1Points(committedSnapshot()).map((p) => ({ ...p, partial: false }));
    assert.deepEqual(q1Segments(points, "strict").dashed, []);
  });
});

describe("numerical claims", () => {
  const facts = q1Facts(committedSnapshot());

  test("reviewed baseline shares", () => {
    assert.equal(facts.latestComplete, 2025);
    assert.equal(facts.partialYear, 2026);
    assert.equal(percent(facts.latest.strict), "35.0%");
    assert.equal(percent(facts.latest.broad), "49.7%");
    assert.equal(percent(facts.partial.strict), "39.8%");
    assert.equal(percent(facts.partial.broad), "54.7%");
  });

  test("rise starts at strict AI's 2015 trough", () => {
    assert.equal(facts.riseStart.strict.year, 2015);
    assert.equal(percent(facts.riseStart.strict.share), "22.5%");
    assert.equal(percent(facts.riseStart.broad.share), "34.7%");
  });

  test("strict AI's 2025 share is below its 1951 share, from full history", () => {
    assert.equal(facts.historyStart, 1950);
    assert.equal(facts.strictEarlierHigh.year, 1951);
    assert.equal(percent(facts.strictEarlierHigh.share), "35.3%");
    assert.ok(facts.strictEarlierHigh.share > facts.latest.strict);
  });
});

describe("claims the snapshot no longer supports", () => {
  test("a different strict trough", () => {
    const snapshot = committedSnapshot();
    setShare(snapshot, 2011, "strict", 0.2);
    rejects(snapshot, /trough is 2011/);
  });

  test("a year without a rise", () => {
    const snapshot = committedSnapshot();
    setShare(snapshot, 2021, "broad", 0.39);
    rejects(snapshot, /broad AI did not rise in 2021/);
  });

  test("broad AI's latest share is not a record", () => {
    const snapshot = committedSnapshot();
    setShare(snapshot, 1955, "broad", 0.5);
    rejects(snapshot, /broad AI's 2025 share is not a record/);
  });

  test("strict AI's latest share becomes a record", () => {
    const snapshot = committedSnapshot();
    for (const r of snapshot.aiShare) if (r.variant === "strict" && r.publication_year < 2025) r.share = Math.min(r.share, 0.34);
    rejects(snapshot, /strict AI's 2025 share is a record/);
  });
});
