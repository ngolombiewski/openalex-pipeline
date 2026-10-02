/**
 * Browser rendering of the Q1 chart. Data arrives as the page's embedded
 * `Q1Point[]`; the chart redraws when its container's width changes.
 */
import * as Plot from "@observablehq/plot";

import { COLORS } from "../palette.ts";
import { percent } from "../format.ts";
import { VARIANT_LABELS, q1Segments, type Q1Point } from "../sections/q1.ts";
import type { Variant } from "../data/snapshot.ts";

const STROKE: Record<Variant, string> = { strict: COLORS.ai, broad: COLORS.broadAi };
const DASH = "4 4";

function render(points: Q1Point[], width: number, height: number): SVGSVGElement | HTMLElement {
  const narrow = width < 560;
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
    marginLeft: 44,
    marginRight: narrow ? 84 : 100,
    marginTop: 24,
    style: { fontFamily: "inherit", fontSize: "13px", fontVariantNumeric: "tabular-nums", background: "transparent" },
    x: { label: null, tickFormat: "d", ticks: narrow ? 5 : 10 },
    y: { label: "Share of CS works", domain: [0, 1], grid: true, tickFormat: (d: number) => `${Math.round(d * 100)}%` },
    marks,
  });
}

export function mountQ1(container: HTMLElement, points: Q1Point[]): void {
  let drawnWidth = 0;
  const draw = () => {
    const width = Math.floor(container.clientWidth);
    if (width === drawnWidth || width === 0) return;
    drawnWidth = width;
    container.replaceChildren(render(points, width, container.clientHeight));
  };
  new ResizeObserver(draw).observe(container);
  draw();
}
