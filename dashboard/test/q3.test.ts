import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { SnapshotDataError, selectQ3, type GiniSubfieldRow, type Snapshot } from "../src/data/snapshot.ts";
import { gini, percent } from "../src/format.ts";
import { AI_ID, CV_PR_ID, GRAPHICS_ID, INFORMATION_SYSTEMS_ID, q3Facts, q3Points } from "../src/sections/q3.ts";
import { committedSnapshot } from "./fixtures.ts";

function cell(snapshot: Snapshot, id: string): GiniSubfieldRow {
  return selectQ3(snapshot).find((r) => r.subfield_id === id)!;
}

function rejects(snapshot: Snapshot, message: RegExp): void {
  assert.throws(
    () => q3Facts(snapshot),
    (error: unknown) => error instanceof SnapshotDataError && /Q3 headline no longer holds/.test(error.message) && message.test(error.message),
  );
}

describe("chart and table agreement", () => {
  test("every table row with a defined Gini is one point with the same values", () => {
    const view = selectQ3(committedSnapshot());
    const { points, omitted } = q3Points(view);
    assert.equal(omitted, 0);
    assert.deepEqual(
      points.map((p) => [p.id, p.name, p.zeroShare, p.giniCitedOnly]),
      view.map((r) => [r.subfield_id, r.subfield_display_name, r.zero_share, r.gini_cited_only]),
    );
  });

  test("labels follow the explicit ID mapping; others are unlabelled", () => {
    const { points } = q3Points(selectQ3(committedSnapshot()));
    const labels = Object.fromEntries(points.filter((p) => p.label).map((p) => [p.id, p.label]));
    assert.deepEqual(labels, {
      [AI_ID]: "AI",
      [CV_PR_ID]: "Computer Vision & PR",
      [GRAPHICS_ID]: "Computer Graphics & CAD",
      [INFORMATION_SYSTEMS_ID]: "Information Systems",
    });
    assert.deepEqual(
      points.filter((p) => p.highlight).map((p) => [p.id, p.highlight]),
      [[AI_ID, "ai"], [CV_PR_ID, "cv_pr"]].sort(),
    );
  });
});

describe("null handling", () => {
  test("an undefined cited-only Gini omits the point and counts it, keeping the row", () => {
    const snapshot = committedSnapshot();
    const view = selectQ3(snapshot);
    view.find((r) => r.subfield_id === "https://openalex.org/subfields/1712")!.gini_cited_only = null;
    const { points, omitted } = q3Points(view);
    assert.equal(omitted, 1);
    assert.equal(points.length, view.length - 1);
    assert.ok(!points.some((p) => p.id.endsWith("/1712")));
  });
});

describe("numerical claims", () => {
  const facts = q3Facts(committedSnapshot());

  test("reviewed cell values", () => {
    assert.equal(facts.subfields, 11);
    assert.equal(percent(facts.ai.zero_share), "46.4%");
    assert.equal(gini(facts.ai.gini_cited_only!), "0.760");
    assert.equal(percent(facts.cvPr.zero_share), "35.3%");
    assert.equal(gini(facts.cvPr.gini_cited_only!), "0.751");
    assert.equal(percent(facts.graphics.zero_share), "67.5%");
    assert.equal(gini(facts.graphics.gini_cited_only!), "0.759");
  });

  test("the fixed cell uses the 2020 cohort and five-year window", () => {
    assert.equal(facts.ai.publication_year, 2020);
    assert.equal(facts.ai.citation_age, 5);
  });
});

describe("claims the snapshot no longer supports", () => {
  test("AI drops out of the three highest cited-only Ginis", () => {
    const snapshot = committedSnapshot();
    cell(snapshot, AI_ID).gini_cited_only = 0.6;
    rejects(snapshot, /AI is not among the three highest/);
  });

  test("CV/PR's uncited share above the median", () => {
    const snapshot = committedSnapshot();
    cell(snapshot, CV_PR_ID).zero_share = 0.6;
    rejects(snapshot, /CV\/PR's uncited share is not below the median/);
  });

  test("Computer Graphics' Gini no longer similar to AI's", () => {
    const snapshot = committedSnapshot();
    cell(snapshot, GRAPHICS_ID).gini_cited_only = 0.7;
    rejects(snapshot, /Computer Graphics' cited-only Gini is not similar/);
  });

  test("Computer Graphics' uncited share close to AI's", () => {
    const snapshot = committedSnapshot();
    cell(snapshot, GRAPHICS_ID).zero_share = 0.5;
    rejects(snapshot, /not substantially larger/);
  });
});

describe("claim threshold boundaries", () => {
  test("a cited-only Gini gap of 0.01 is not similar; just under is", () => {
    const snapshot = committedSnapshot();
    cell(snapshot, AI_ID).gini_cited_only = 0.75;
    cell(snapshot, GRAPHICS_ID).gini_cited_only = 0.76;
    rejects(snapshot, /Computer Graphics' cited-only Gini is not similar/);
    cell(snapshot, GRAPHICS_ID).gini_cited_only = 0.759;
    assert.doesNotThrow(() => q3Facts(snapshot));
  });

  test("an uncited-share gap of exactly 0.1 is substantially larger; just under is not", () => {
    const snapshot = committedSnapshot();
    // 0.304 - 0.204 === 0.1 in floating point.
    cell(snapshot, AI_ID).zero_share = 0.204;
    cell(snapshot, GRAPHICS_ID).zero_share = 0.304;
    assert.doesNotThrow(() => q3Facts(snapshot));
    cell(snapshot, GRAPHICS_ID).zero_share = 0.303;
    rejects(snapshot, /not substantially larger/);
  });
});
