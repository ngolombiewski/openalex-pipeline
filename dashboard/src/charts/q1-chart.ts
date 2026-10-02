/**
 * Browser rendering of the Q1 chart. Data arrives as the page's embedded
 * `Q1Point[]`.
 */
import * as Plot from "@observablehq/plot";

import { mountChart } from "./mount.ts";
import { COLORS } from "../palette.ts";
import { percent } from "../format.ts";
import { VARIANT_LABELS, q1Segments, type Q1Point } from "../sections/q1.ts";
import type { Variant } from "../data/snapshot.ts";

const STROKE: Record<Variant, string> = { strict: COLORS.ai, broad: COLORS.broadAi };
const DASH = "4 4";
const MARGIN_LEFT = 62;

/** Year ticks: first, a round middle year, and last on a narrow plot; Plot's choice otherwise. */
function yearTicks(points: Q1Point[], plotWidth: number): number[] | number {
  if (plotWidth >= 300) return 10;
  const years = points.map((p) => p.year);
  const first = Math.min(...years);
  const last = Math.max(...years);
  return [first, Math.round((first + last) / 20) * 10, last];
}

function render(points: Q1Point[], width: number, height: number): Element {
  const narrow = width < 560;
  const marginRight = narrow ? 84 : 100;
  const marks: Plot.Markish[] = [Plot.ruleY([0], { stroke: "currentColor", strokeOpacity: 0.4 })];
  for (const variant of ["broad", "strict"] as const) {
    const { solid, dashed } = q1Segments(points, variant);
    const last = dashed[dashed.length - 1] ?? solid[solid.length - 1]!;
    const stroke = STROKE[variant];
    marks.push(
      Plot.line(solid, { x: "year", y: "share", stroke, strokeWidth: 2.25 }),
      Plot.line(dashed, { x: "year", y: "share", stroke, strokeWidth: 2.25, strokeDasharray: DASH }),
      Plot.dot(dashed.slice(1), { x: "year", y: "share", stroke, fill: COLORS.paper, strokeWidth: 2, r: 4 }),
      Plot.text([last], {
        x: "year",
        y: "share",
        text: () => VARIANT_LABELS[variant],
        fill: stroke,
        dx: 8,
        textAnchor: "start",
        fontWeight: 600,
      }),
    );
  }
  const partial = points.filter((p) => p.partial);
  if (partial.length > 0) {
    const top = partial.reduce((a, b) => (a.share > b.share ? a : b));
    marks.push(
      Plot.text([top], {
        x: "year",
        y: "share",
        text: (p: Q1Point) => `${p.year}, partial`,
        dy: -14,
        textAnchor: "end",
        fill: "currentColor",
        fillOpacity: 0.75,
      }),
    );
  }
  marks.push(
    Plot.tip(
      points,
      Plot.pointerX({
        x: "year",
        y: "share",
        title: (p: Q1Point) => `${p.year}${p.partial ? " (partial)" : ""}\n${VARIANT_LABELS[p.variant]}: ${percent(p.share)}`,
      }),
    ),
  );
  return Plot.plot({
    width,
    height,
    marginLeft: MARGIN_LEFT,
    marginRight,
    marginTop: 24,
    style: { fontFamily: "inherit", fontSize: "13px", fontVariantNumeric: "tabular-nums", background: "transparent" },
    x: { label: null, tickFormat: "d", ticks: yearTicks(points, width - MARGIN_LEFT - marginRight) },
    y: { label: "Share of CS works", domain: [0, 1], grid: true, ticks: [0, 0.25, 0.5, 0.75, 1], tickFormat: percent },
    marks,
  });
}

export function mountQ1(container: HTMLElement, points: Q1Point[]): void {
  mountChart(container, (width, height) => render(points, width, height));
}
