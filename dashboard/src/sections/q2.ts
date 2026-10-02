/**
 * Q2 — the age of work receiving citation attention.
 *
 * The chart and the exact-value table both read `selectQ2`'s view. `q2Facts`
 * supplies every number the Q2 prose states and asserts the claims that prose
 * makes, throwing `SnapshotDataError` when the snapshot no longer supports them.
 */
import { CITED_GROUPS, SnapshotDataError, selectQ2, type CitationAgeRow, type CitedGroup, type Snapshot } from "../data/snapshot.ts";

const FILE = "gold_citation_age_by_year.json";

export interface Q2Point {
  year: number;
  group: CitedGroup;
  median: number;
}

/** The Q2 view as chart points, in the view's order (year, then group). */
export function q2Points(view: CitationAgeRow[]): Q2Point[] {
  return view.map((r) => ({ year: r.citation_year, group: r.cited_group, median: r.median_citation_age }));
}

/**
 * Vertical label offsets, in label steps, for the series' end labels:
 * groups ending on the same median are spread symmetrically around it, in
 * `CITED_GROUPS` order; a group with a distinct final median gets 0.
 */
export function q2LabelOffsets(points: Q2Point[]): Record<CitedGroup, number> {
  const lastYear = Math.max(...points.map((p) => p.year));
  const final = (group: CitedGroup) => points.find((p) => p.year === lastYear && p.group === group)!.median;
  const offsets = {} as Record<CitedGroup, number>;
  for (const group of CITED_GROUPS) {
    const tied = CITED_GROUPS.filter((g) => final(g) === final(group));
    offsets[group] = tied.indexOf(group) - (tied.length - 1) / 2;
  }
  return offsets;
}

export interface Q2Facts {
  firstYear: number;
  lastYear: number;
  firstMedian: Record<CitedGroup, number>;
  lastMedian: Record<CitedGroup, number>;
  /** `share_age_lte_5` in `lastYear`. */
  lastShareLte5: Record<CitedGroup, number>;
}

/**
 * Numbers and checked claims for the Q2 prose:
 *
 * - every group's median citation age is lower in the last year than the first;
 * - in the first year AI's median is above both other groups';
 * - in the last year all three medians are equal.
 */
export function q2Facts(snapshot: Snapshot): Q2Facts {
  const view = selectQ2(snapshot);
  const { citation_age_year_min: firstYear, citation_age_year_max: lastYear } = snapshot.meta.bounds;
  const fail = (claim: string): never => {
    throw new SnapshotDataError(FILE, `Q2 headline no longer holds: ${claim}`);
  };
  const row = (year: number, group: CitedGroup) => view.find((r) => r.citation_year === year && r.cited_group === group)!;
  const byGroup = <T>(pick: (group: CitedGroup) => T) =>
    Object.fromEntries(CITED_GROUPS.map((g) => [g, pick(g)])) as Record<CitedGroup, T>;

  const firstMedian = byGroup((g) => row(firstYear, g).median_citation_age);
  const lastMedian = byGroup((g) => row(lastYear, g).median_citation_age);
  for (const group of CITED_GROUPS) {
    if (lastMedian[group] >= firstMedian[group]) fail(`${group} median did not fall from ${firstYear} to ${lastYear}`);
  }
  if (firstMedian.ai <= Math.max(firstMedian.cv_pr, firstMedian.rest_cs)) fail(`AI's ${firstYear} median is not the oldest`);
  if (new Set(Object.values(lastMedian)).size !== 1) fail(`${lastYear} medians differ`);

  return { firstYear, lastYear, firstMedian, lastMedian, lastShareLte5: byGroup((g) => row(lastYear, g).share_age_lte_5) };
}
