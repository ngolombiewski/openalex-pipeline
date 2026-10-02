/** Browser rendering of the Q3 scatter from the page's embedded `Q3Point[]`. */
import * as Plot from "@observablehq/plot";

import { mountChart } from "./mount.ts";
import { gini, percent } from "../format.ts";
import { COLORS } from "../palette.ts";
import { GROUP_COLORS, GROUP_SYMBOLS } from "../sections/groups.ts";
import { AI_ID, CV_PR_ID, GRAPHICS_ID, INFORMATION_SYSTEMS_ID, type Q3Point } from "../sections/q3.ts";

type Placement = { x: number; y: number; leader: [number, number]; wrap: boolean; textAnchor: "start" | "middle" | "end"; lineAnchor: "top" | "bottom" };

/**
 * Hand-placed annotations for the labelled subfields, in data coordinates,
 * fixed for the committed cell. A leader runs from each point to `leader`,
 * just short of its label.
 *
 * On a wide plot each label sits beside its point on one line. On a narrow one
 * the points cluster too tightly for that, so each label moves to its own empty
 * region, wrapped where `wrap` is set; these hold down to a 320px viewport.
 */
const WIDE: Record<string, Placement> = {
  [AI_ID]: { x: 0.465, y: 0.82, leader: [0.465, 0.81], wrap: false, textAnchor: "middle", lineAnchor: "bottom" },
  [GRAPHICS_ID]: { x: 0.72, y: 0.83, leader: [0.715, 0.82], wrap: false, textAnchor: "start", lineAnchor: "bottom" },
  [CV_PR_ID]: { x: 0.33, y: 0.83, leader: [0.335, 0.82], wrap: false, textAnchor: "end", lineAnchor: "bottom" },
  [INFORMATION_SYSTEMS_ID]: { x: 0.66, y: 0.68, leader: [0.655, 0.69], wrap: false, textAnchor: "start", lineAnchor: "top" },
};
const NARROW: Record<string, Placement> = {
  [AI_ID]: { x: 0.46, y: 0.95, leader: [0.46, 0.93], wrap: false, textAnchor: "middle", lineAnchor: "bottom" },
  [GRAPHICS_ID]: { x: 0.98, y: 0.86, leader: [0.8, 0.84], wrap: true, textAnchor: "end", lineAnchor: "bottom" },
  [CV_PR_ID]: { x: 0.02, y: 0.58, leader: [0.12, 0.6], wrap: true, textAnchor: "start", lineAnchor: "top" },
  [INFORMATION_SYSTEMS_ID]: { x: 0.98, y: 0.58, leader: [0.85, 0.6], wrap: true, textAnchor: "end", lineAnchor: "top" },
};
const MARGIN_LEFT = 48;
const MARGIN_RIGHT = 24;
/** Plot width from which the one-line placements fit. */
const WIDE_FROM = 560;

/** Few ticks, so they fit at the approved precision on a narrow screen. */
const TICKS = [0, 0.25, 0.5, 0.75, 1];

function render(points: Q3Point[], width: number, height: number): Element {
  const plain = points.filter((p) => p.highlight === null);
  const highlighted = points.filter((p) => p.highlight !== null);
  const labelled = points.filter((p) => p.label !== null);
  const placement = width - MARGIN_LEFT - MARGIN_RIGHT >= WIDE_FROM ? WIDE : NARROW;
  return Plot.plot({
    width,
    height,
    marginLeft: MARGIN_LEFT,
    marginRight: MARGIN_RIGHT,
    marginTop: 24,
    marginBottom: 44,
    style: { fontFamily: "inherit", fontSize: "13px", fontVariantNumeric: "tabular-nums", background: "transparent" },
    x: { label: "Share with no citations in years 1–5", domain: [0, 1], grid: true, ticks: TICKS, tickFormat: percent, labelAnchor: "center" },
    y: { label: "Gini among cited papers", domain: [0, 1], grid: true, ticks: TICKS, tickFormat: gini },
    symbol: { type: "identity" },
    marks: [
      ...labelled.map((p) => {
        const { leader } = placement[p.id]!;
        return Plot.link([p], { x1: "zeroShare", y1: "giniCitedOnly", x2: () => leader[0], y2: () => leader[1], stroke: "currentColor", strokeOpacity: 0.5 });
      }),
      Plot.dot(plain, { x: "zeroShare", y: "giniCitedOnly", fill: COLORS.neutral, r: 5 }),
      Plot.dot(highlighted, {
        x: "zeroShare",
        y: "giniCitedOnly",
        fill: (p: Q3Point) => GROUP_COLORS[p.highlight!],
        symbol: (p: Q3Point) => GROUP_SYMBOLS[p.highlight!],
        r: 7,
      }),
      ...labelled.map((p) => {
        const { x, y, wrap, textAnchor, lineAnchor } = placement[p.id]!;
        return Plot.text([p], {
          x: () => x,
          y: () => y,
          text: () => (wrap ? p.label!.replace(" ", "\n") : p.label!),
          fill: p.highlight ? GROUP_COLORS[p.highlight] : "currentColor",
          fontWeight: p.highlight ? 650 : 500,
          textAnchor,
          lineAnchor,
        });
      }),
      Plot.tip(
        points,
        Plot.pointer({
          x: "zeroShare",
          y: "giniCitedOnly",
          title: (p: Q3Point) => `${p.name}\nUncited in years 1–5: ${percent(p.zeroShare)}\nGini among cited: ${gini(p.giniCitedOnly)}`,
        }),
      ),
    ],
  });
}

export function mountQ3(container: HTMLElement, points: Q3Point[]): void {
  mountChart(container, (width, height) => render(points, width, height));
}
