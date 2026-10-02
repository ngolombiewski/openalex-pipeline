/**
 * Q1 — AI's share of CS output.
 *
 * `q1Points` feeds both the chart and the detail table, so they show the
 * same years, variants, and shares. `q1Facts` supplies every number the Q1
 * prose states and asserts the claims that prose makes; if the snapshot no
 * longer supports them it throws `SnapshotDataError`, stopping the build for
 * content review instead of rewording the story.
 */
import { SnapshotDataError, VARIANTS, selectQ1, type AiShareRow, type Snapshot, type Variant } from "../data/snapshot.ts";

const FILE = "gold_ai_share_by_year.json";

/** The year the authored prose names as strict AI's trough and the start of the rise. */
export const Q1_TROUGH_YEAR = 2015;

/** Display labels for the gold variants: strict is AI only, broad is AI + CV/PR. */
export const VARIANT_LABELS: Record<Variant, string> = {
  strict: "AI only",
  broad: "AI + CV/PR",
};

export interface Q1Point {
  year: number;
  variant: Variant;
  share: number;
  aiWorks: number;
  csWorks: number;
  partial: boolean;
}

/** The Q1 view as chart/table points, in the view's order (year, then variant). */
export function q1Points(snapshot: Snapshot): Q1Point[] {
  return selectQ1(snapshot).map((row) => ({
    year: row.publication_year,
    variant: row.variant,
    share: row.share,
    aiWorks: row.ai_works,
    csWorks: row.cs_works,
    partial: row.is_partial_year,
  }));
}

/**
 * Split one variant's points for drawing: `solid` holds the complete years;
 * `dashed` joins the last complete year to the partial year.
 */
export function q1Segments(points: Q1Point[], variant: Variant): { solid: Q1Point[]; dashed: Q1Point[] } {
  const series = points.filter((p) => p.variant === variant);
  const solid = series.filter((p) => !p.partial);
  const partial = series.filter((p) => p.partial);
  return { solid, dashed: partial.length > 0 ? [solid[solid.length - 1]!, ...partial] : [] };
}

interface YearShare {
  year: number;
  share: number;
}

export interface Q1Facts {
  firstYear: number;
  latestComplete: number;
  partialYear: number;
  /** Both shares in `Q1_TROUGH_YEAR`, where the rise starts. */
  riseStart: Record<Variant, YearShare>;
  latest: Record<Variant, number>;
  partial: Record<Variant, number>;
  /** Strict AI's highest complete-year share before `latestComplete`, from full history. */
  strictEarlierHigh: YearShare;
  /** First year of the full exported history, for the record claim. */
  historyStart: number;
}

/**
 * Numbers and checked claims for the Q1 prose:
 *
 * - strict AI's lowest displayed complete-year share is in `Q1_TROUGH_YEAR`;
 * - both variants rise every year from `Q1_TROUGH_YEAR` to the last complete year;
 * - broad AI's last complete year is the highest complete year in full history;
 * - strict AI's last complete year is below an earlier complete year.
 */
export function q1Facts(snapshot: Snapshot): Q1Facts {
  const { year_min, partial_year } = snapshot.meta.bounds;
  const latestComplete = partial_year - 1;
  const view = q1Points(snapshot);
  const fail = (claim: string): never => {
    throw new SnapshotDataError(FILE, `Q1 headline no longer holds: ${claim}`);
  };
  const at = (rows: { year: number; variant: Variant; share: number }[], year: number, variant: Variant): number =>
    rows.find((p) => p.year === year && p.variant === variant)?.share ?? fail(`no ${year} × ${variant}`);

  const complete = view.filter((p) => !p.partial);
  const strictLow = complete
    .filter((p) => p.variant === "strict")
    .reduce((low, p) => (p.share < low.share ? p : low));
  if (strictLow.year !== Q1_TROUGH_YEAR) fail(`strict AI's trough is ${strictLow.year}, not ${Q1_TROUGH_YEAR}`);

  for (const variant of VARIANTS) {
    for (let year = Q1_TROUGH_YEAR + 1; year <= latestComplete; year++) {
      if (at(view, year, variant) <= at(view, year - 1, variant)) fail(`${variant} AI did not rise in ${year}`);
    }
  }

  const history = snapshot.aiShare
    .filter((r: AiShareRow) => !r.is_partial_year)
    .map((r) => ({ year: r.publication_year, variant: r.variant, share: r.share }));
  const earlier = (variant: Variant) => history.filter((r) => r.variant === variant && r.year < latestComplete);
  const latest = { strict: at(view, latestComplete, "strict"), broad: at(view, latestComplete, "broad") };

  if (earlier("broad").some((r) => r.share >= latest.broad)) fail(`broad AI's ${latestComplete} share is not a record`);
  const strictHigh = earlier("strict").reduce((high, r) => (r.share > high.share ? r : high));
  if (strictHigh.share <= latest.strict) fail(`strict AI's ${latestComplete} share is a record`);

  return {
    firstYear: view[0]!.year,
    latestComplete,
    partialYear: partial_year,
    riseStart: {
      strict: { year: Q1_TROUGH_YEAR, share: at(view, Q1_TROUGH_YEAR, "strict") },
      broad: { year: Q1_TROUGH_YEAR, share: at(view, Q1_TROUGH_YEAR, "broad") },
    },
    latest,
    partial: { strict: at(view, partial_year, "strict"), broad: at(view, partial_year, "broad") },
    strictEarlierHigh: { year: strictHigh.year, share: strictHigh.share },
    historyStart: year_min,
  };
}
