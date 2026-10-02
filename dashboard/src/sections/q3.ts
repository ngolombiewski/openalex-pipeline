/**
 * Q3 — citation reach and concentration across CS subfields.
 *
 * The chart and the exact-value table both read `selectQ3`'s fixed cell.
 * Subfield identity is the subfield ID; `Q3_CHART_LABELS` is the explicit map
 * of chart annotations, and the table always shows the published display name.
 * `q3Facts` supplies every number the Q3 prose states and asserts the claims
 * that prose makes, throwing `SnapshotDataError` when the snapshot no longer
 * supports them.
 */
import { SnapshotDataError, selectQ3, type CitedGroup, type GiniSubfieldRow, type Snapshot } from "../data/snapshot.ts";

const FILE = "gold_citation_gini_by_subfield.json";

export const AI_ID = "https://openalex.org/subfields/1702";
export const CV_PR_ID = "https://openalex.org/subfields/1707";
export const GRAPHICS_ID = "https://openalex.org/subfields/1704";
export const INFORMATION_SYSTEMS_ID = "https://openalex.org/subfields/1710";

export const Q3_CHART_LABELS: Record<string, string> = {
  [AI_ID]: "AI",
  [CV_PR_ID]: "Computer Vision & PR",
  [GRAPHICS_ID]: "Computer Graphics & CAD",
  [INFORMATION_SYSTEMS_ID]: "Information Systems",
};

/** Subfields drawn in a group's colour and shape; all others are neutral. */
const HIGHLIGHTED: Record<string, CitedGroup> = { [AI_ID]: "ai", [CV_PR_ID]: "cv_pr" };

export interface Q3Point {
  id: string;
  name: string;
  /** Chart annotation, or null when the subfield is not labelled. */
  label: string | null;
  highlight: CitedGroup | null;
  zeroShare: number;
  giniCitedOnly: number;
}

/**
 * Scatter points for subfields whose cited-only Gini is defined, and the
 * number omitted because it is null (no cited papers).
 */
export function q3Points(view: GiniSubfieldRow[]): { points: Q3Point[]; omitted: number } {
  const points: Q3Point[] = [];
  for (const r of view) {
    if (r.gini_cited_only === null) continue;
    points.push({
      id: r.subfield_id,
      name: r.subfield_display_name,
      label: Q3_CHART_LABELS[r.subfield_id] ?? null,
      highlight: HIGHLIGHTED[r.subfield_id] ?? null,
      zeroShare: r.zero_share,
      giniCitedOnly: r.gini_cited_only,
    });
  }
  return { points, omitted: view.length - points.length };
}

export interface Q3Facts {
  subfields: number;
  ai: GiniSubfieldRow;
  cvPr: GiniSubfieldRow;
  graphics: GiniSubfieldRow;
}

/** Cited-only Ginis closer than this read as "similar" in the prose. */
const SIMILAR_GINI = 0.01;
/** Uncited shares at least this much larger read as "substantially larger". */
const LARGER_ZERO_SHARE = 0.1;

/**
 * Numbers and checked claims for the Q3 prose, against unrounded values:
 *
 * - AI and CV/PR are among the three highest cited-only Ginis in the cell;
 * - both have an uncited share below the cell's median subfield;
 * - Computer Graphics' cited-only Gini is within `SIMILAR_GINI` of AI's, and its
 *   uncited share exceeds AI's by at least `LARGER_ZERO_SHARE`.
 */
export function q3Facts(snapshot: Snapshot): Q3Facts {
  const view = selectQ3(snapshot);
  const fail = (claim: string): never => {
    throw new SnapshotDataError(FILE, `Q3 headline no longer holds: ${claim}`);
  };
  const get = (id: string) => view.find((r) => r.subfield_id === id)!;
  const ai = get(AI_ID);
  const cvPr = get(CV_PR_ID);
  const graphics = get(GRAPHICS_ID);

  const ginis = view.map((r) => r.gini_cited_only).filter((g): g is number => g !== null);
  const third = [...ginis].sort((a, b) => b - a)[2]!;
  const zeros = view.map((r) => r.zero_share).sort((a, b) => a - b);
  const median = zeros.length % 2 ? zeros[(zeros.length - 1) / 2]! : (zeros[zeros.length / 2 - 1]! + zeros[zeros.length / 2]!) / 2;

  for (const [name, row] of [["AI", ai], ["CV/PR", cvPr]] as const) {
    if (row.gini_cited_only === null || row.gini_cited_only < third) fail(`${name} is not among the three highest cited-only Ginis`);
    if (row.zero_share >= median) fail(`${name}'s uncited share is not below the median subfield`);
  }
  if (graphics.gini_cited_only === null || Math.abs(graphics.gini_cited_only - ai.gini_cited_only!) >= SIMILAR_GINI) {
    fail("Computer Graphics' cited-only Gini is not similar to AI's");
  }
  if (graphics.zero_share - ai.zero_share < LARGER_ZERO_SHARE) fail("Computer Graphics' uncited share is not substantially larger than AI's");

  return { subfields: view.length, ai, cvPr, graphics };
}
