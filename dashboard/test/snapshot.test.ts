import assert from "node:assert/strict";
import { describe, test } from "node:test";

import aiShare from "../data/gold_ai_share_by_year.json" with { type: "json" };
import citationAge from "../data/gold_citation_age_by_year.json" with { type: "json" };
import giniByGroup from "../data/gold_citation_gini_by_group.json" with { type: "json" };
import giniBySubfield from "../data/gold_citation_gini_by_subfield.json" with { type: "json" };
import meta from "../data/snapshot.json" with { type: "json" };
import {
  CITED_GROUPS,
  Q1_FIRST_YEAR,
  Q3_COHORT,
  Q3_LABELLED_SUBFIELD_IDS,
  Q3_WINDOW,
  SnapshotDataError,
  parseSnapshot,
  selectQ1,
  selectQ2,
  selectQ3,
} from "../src/data/snapshot.ts";

type Rows = Record<string, unknown>[];
type Files = Record<string, unknown>;

/** A deep copy of the committed snapshot, safe to mutate per test. */
function committed(): Files {
  return structuredClone({
    "snapshot.json": meta,
    "gold_ai_share_by_year.json": aiShare,
    "gold_citation_age_by_year.json": citationAge,
    "gold_citation_gini_by_subfield.json": giniBySubfield,
    "gold_citation_gini_by_group.json": giniByGroup,
  });
}

function rows(files: Files, relation: string): Rows {
  return files[`${relation}.json`] as Rows;
}

/** Remove rows matching `predicate` and keep the recorded count consistent. */
function dropRows(files: Files, relation: string, predicate: (row: Record<string, unknown>) => boolean): void {
  const kept = rows(files, relation).filter((row) => !predicate(row));
  files[`${relation}.json`] = kept;
  ((files["snapshot.json"] as Record<string, unknown>).row_counts as Record<string, number>)[relation] = kept.length;
}

function bounds(files: Files): Record<string, number> {
  return (files["snapshot.json"] as Record<string, unknown>).bounds as Record<string, number>;
}

function rejects(files: Files, file: string, message: RegExp): void {
  assert.throws(
    () => parseSnapshot(files),
    (error: unknown) =>
      error instanceof SnapshotDataError && error.file === file && message.test(error.message),
  );
}

describe("committed snapshot", () => {
  const snapshot = parseSnapshot(committed());

  test("parses with recorded row counts", () => {
    assert.equal(snapshot.aiShare.length, meta.row_counts.gold_ai_share_by_year);
    assert.equal(snapshot.giniBySubfield.length, meta.row_counts.gold_citation_gini_by_subfield);
  });

  test("Q1 view covers both variants from 1980 through the partial year", () => {
    const view = selectQ1(snapshot);
    const years = meta.bounds.year_max - Q1_FIRST_YEAR + 1;
    assert.equal(view.length, years * 2);
    assert.equal(view[0]?.publication_year, Q1_FIRST_YEAR);
    assert.deepEqual(
      view.filter((row) => row.is_partial_year).map((row) => row.publication_year),
      [meta.bounds.partial_year, meta.bounds.partial_year],
    );
  });

  test("Q2 view covers every group in every citation year", () => {
    const view = selectQ2(snapshot);
    const years = meta.bounds.citation_age_year_max - meta.bounds.citation_age_year_min + 1;
    assert.equal(view.length, years * CITED_GROUPS.length);
  });

  test("Q3 view is the classified 2020/5 cell including labelled subfields", () => {
    const view = selectQ3(snapshot);
    assert.ok(view.every((row) => row.publication_year === Q3_COHORT && row.citation_age === Q3_WINDOW));
    assert.ok(view.every((row) => row.subfield_id.startsWith("https://openalex.org/subfields/")));
    for (const id of Q3_LABELLED_SUBFIELD_IDS) assert.ok(view.some((row) => row.subfield_id === id));
  });
});

describe("file boundary", () => {
  test("missing file", () => {
    const files = committed();
    delete files["gold_citation_age_by_year.json"];
    rejects(files, "gold_citation_age_by_year.json", /file is missing/);
  });

  test("missing snapshot.json", () => {
    const files = committed();
    delete files["snapshot.json"];
    rejects(files, "snapshot.json", /file is missing/);
  });

  test("empty relation", () => {
    const files = committed();
    dropRows(files, "gold_citation_gini_by_group", () => true);
    rejects(files, "gold_citation_gini_by_group.json", /relation is empty/);
  });

  test("extra column", () => {
    const files = committed();
    rows(files, "gold_ai_share_by_year")[0]!.extra = 1;
    rejects(files, "gold_ai_share_by_year.json", /row 0 columns/);
  });

  test("missing column", () => {
    const files = committed();
    delete rows(files, "gold_ai_share_by_year")[0]!.share;
    rejects(files, "gold_ai_share_by_year.json", /row 0 columns/);
  });

  test("integer serialized as string", () => {
    const files = committed();
    rows(files, "gold_citation_age_by_year")[0]!.citation_events = "123";
    rejects(files, "gold_citation_age_by_year.json", /citation_events="123" is not int/);
  });

  test("fractional value in integer column", () => {
    const files = committed();
    rows(files, "gold_citation_age_by_year")[0]!.median_citation_age = 5.5;
    rejects(files, "gold_citation_age_by_year.json", /median_citation_age=5.5 is not int/);
  });

  test("null in non-nullable column", () => {
    const files = committed();
    rows(files, "gold_citation_gini_by_subfield")[0]!.zero_share = null;
    rejects(files, "gold_citation_gini_by_subfield.json", /zero_share is null/);
  });

  test("null in nullable ratio is accepted", () => {
    const files = committed();
    const row = rows(files, "gold_citation_gini_by_subfield").find(
      (r) => r.publication_year === Q3_COHORT && r.citation_age === Q3_WINDOW,
    )!;
    row.gini = null;
    row.gini_cited_only = null;
    row.top1_share = null;
    const snapshot = parseSnapshot(files);
    assert.ok(selectQ3(snapshot).some((r) => r.gini_cited_only === null));
  });

  test("unknown cited group", () => {
    const files = committed();
    rows(files, "gold_citation_gini_by_group")[0]!.cited_group = "other";
    rejects(files, "gold_citation_gini_by_group.json", /cited_group="other" is not one of/);
  });

  test("duplicate grain key", () => {
    const files = committed();
    const relation = rows(files, "gold_ai_share_by_year");
    relation.push({ ...relation[0]! });
    ((files["snapshot.json"] as Record<string, unknown>).row_counts as Record<string, number>).gold_ai_share_by_year =
      relation.length;
    rejects(files, "gold_ai_share_by_year.json", /duplicate grain key/);
  });

  test("row count differs from snapshot.json", () => {
    const files = committed();
    rows(files, "gold_citation_age_by_year").pop();
    rejects(files, "gold_citation_age_by_year.json", /rows != recorded/);
  });

  test("empty pipeline revision", () => {
    const files = committed();
    (files["snapshot.json"] as Record<string, unknown>).pipeline_revision = "";
    rejects(files, "snapshot.json", /pipeline_revision is empty/);
  });

  test("missing bound", () => {
    const files = committed();
    delete ((files["snapshot.json"] as Record<string, unknown>).bounds as Record<string, unknown>).partial_year;
    rejects(files, "snapshot.json", /bounds must name exactly/);
  });
});

describe("recorded bounds", () => {
  test("Q1 publication years differ from recorded range", () => {
    const files = committed();
    bounds(files).year_min = 1960;
    rejects(files, "gold_ai_share_by_year.json", /publication years 1950..2026 != recorded 1960..2026/);
  });

  test("Q2 citation years differ from recorded range", () => {
    const files = committed();
    bounds(files).citation_age_year_max = 2024;
    rejects(files, "gold_citation_age_by_year.json", /citation years 2012..2025 != recorded 2012..2024/);
  });

  test("inverted Q2 range", () => {
    const files = committed();
    bounds(files).citation_age_year_min = 2026;
    rejects(files, "gold_citation_age_by_year.json", /citation years/);
  });

  test("Q3 cohorts below the recorded floor", () => {
    const files = committed();
    bounds(files).gini_cohort_min = 2021;
    rejects(files, "gold_citation_gini_by_subfield.json", /cohorts 2012..2024 != recorded 2021..2024/);
  });

  test("Q3 citation-year ceiling beyond the data", () => {
    const files = committed();
    bounds(files).gini_citation_year_max = 2026;
    rejects(files, "gold_citation_gini_by_subfield.json", /cohorts/);
  });

  test("Q3 citation window beyond the recorded ceiling", () => {
    const files = committed();
    const relation = rows(files, "gold_citation_gini_by_group");
    relation.push({ ...relation.find((r) => r.publication_year === Q3_COHORT && r.citation_age === Q3_WINDOW)!, citation_age: 6 });
    ((files["snapshot.json"] as Record<string, unknown>).row_counts as Record<string, number>).gold_citation_gini_by_group =
      relation.length;
    rejects(files, "gold_citation_gini_by_group.json", /last citation year 2026 != recorded 2025/);
  });

  test("one variant loses the partial-year flag", () => {
    const files = committed();
    const row = rows(files, "gold_ai_share_by_year").find((r) => r.publication_year === 2026 && r.variant === "strict")!;
    row.is_partial_year = false;
    rejects(files, "gold_ai_share_by_year.json", /partial-year flag disagrees with 2026 on 2026 × strict/);
  });

  test("an earlier row gains the partial-year flag", () => {
    const files = committed();
    rows(files, "gold_ai_share_by_year").find((r) => r.publication_year === 2025)!.is_partial_year = true;
    rejects(files, "gold_ai_share_by_year.json", /partial-year flag disagrees with 2026 on 2025 × /);
  });
});

describe("fixed views", () => {
  test("Q1 year missing a variant", () => {
    const files = committed();
    dropRows(files, "gold_ai_share_by_year", (r) => r.publication_year === 1990 && r.variant === "broad");
    rejects(files, "gold_ai_share_by_year.json", /missing 1990 × broad/);
  });

  test("Q1 partial year that is not the last year", () => {
    const snapshot = parseSnapshot(committed());
    snapshot.meta.bounds.partial_year = 2025;
    assert.throws(
      () => selectQ1(snapshot),
      (error: unknown) => error instanceof SnapshotDataError && /partial year 2025 is not the last year/.test(error.message),
    );
  });

  test("Q2 year missing a group", () => {
    const files = committed();
    dropRows(files, "gold_citation_age_by_year", (r) => r.citation_year === 2018 && r.cited_group === "cv_pr");
    rejects(files, "gold_citation_age_by_year.json", /missing 2018 × cv_pr/);
  });

  test("Q3 cell missing a labelled subfield", () => {
    const files = committed();
    dropRows(
      files,
      "gold_citation_gini_by_subfield",
      (r) =>
        r.publication_year === Q3_COHORT &&
        r.citation_age === Q3_WINDOW &&
        r.subfield_id === "https://openalex.org/subfields/1710",
    );
    rejects(files, "gold_citation_gini_by_subfield.json", /missing https:\/\/openalex.org\/subfields\/1710/);
  });

  test("Q3 cell missing an unlabelled subfield", () => {
    const files = committed();
    dropRows(
      files,
      "gold_citation_gini_by_subfield",
      (r) =>
        r.publication_year === Q3_COHORT &&
        r.citation_age === Q3_WINDOW &&
        r.subfield_id === "https://openalex.org/subfields/1712",
    );
    rejects(files, "gold_citation_gini_by_subfield.json", /missing https:\/\/openalex.org\/subfields\/1712/);
  });

  test("Q3 cell beyond the citation-year ceiling", () => {
    const snapshot = parseSnapshot(committed());
    snapshot.meta.bounds.gini_citation_year_max = Q3_COHORT + Q3_WINDOW - 1;
    assert.throws(
      () => selectQ3(snapshot),
      (error: unknown) => error instanceof SnapshotDataError && /ends after citation year/.test(error.message),
    );
  });

  test("Q3 view excludes the unclassified bucket", () => {
    const files = committed();
    const template = rows(files, "gold_citation_gini_by_subfield").find(
      (r) => r.publication_year === Q3_COHORT && r.citation_age === Q3_WINDOW,
    )!;
    rows(files, "gold_citation_gini_by_subfield").push({
      ...template,
      subfield_id: "__unclassified__",
      subfield_display_name: "Unclassified",
    });
    ((files["snapshot.json"] as Record<string, unknown>).row_counts as Record<string, number>)
      .gold_citation_gini_by_subfield += 1;
    const view = selectQ3(parseSnapshot(files));
    assert.ok(view.every((row) => row.subfield_id !== "__unclassified__"));
  });
});
