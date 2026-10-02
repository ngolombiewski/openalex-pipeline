/** Browser rendering of the Q2 chart from the page's embedded `Q2Point[]`. */
import * as Plot from "@observablehq/plot";

import { mountChart } from "./mount.ts";
import { CITED_GROUPS, type CitedGroup } from "../data/snapshot.ts";
import { COLORS } from "../palette.ts";
import { GROUP_COLORS, GROUP_LABELS, GROUP_SYMBOLS } from "../sections/groups.ts";
import { q2LabelOffsets, type Q2Point } from "../sections/q2.ts";

const LABEL_STEP = 15;
const MARGIN_LEFT = 44;
const MARGIN_RIGHT = 90;

/**
 * Per-group line and marker styling that keeps coincident series apart.
 * Medians are whole years and often tie, so lines are drawn widest-dash first
 * and markers largest first: where groups coincide the dashes interleave and
 * the markers nest (circle around triangle around square) instead of covering
 * one another. Ages are never jittered.
 */
const DRAW_ORDER: CitedGroup[] = ["rest_cs", "cv_pr", "ai"];
const DASH: Record<CitedGroup, string | undefined> = { rest_cs: undefined, cv_pr: "7,4", ai: "2,3" };
const MARKER_R: Record<CitedGroup, number> = { rest_cs: 6, cv_pr: 4.75, ai: 2.75 };

/** Year ticks: first, middle, and last on a narrow plot; Plot's choice otherwise. */
function yearTicks(points: Q2Point[], plotWidth: number): number[] | number {
  if (plotWidth >= 360) return 8;
  const years = points.map((p) => p.year);
  const first = Math.min(...years);
  const last = Math.max(...years);
  return [first, Math.floor((first + last) / 2), last];
}

function render(points: Q2Point[], width: number, height: number): Element {
  const lastYear = Math.max(...points.map((p) => p.year));
  const offsets = q2LabelOffsets(points);
  const marks: Plot.Markish[] = [Plot.ruleY([0], { stroke: "currentColor", strokeOpacity: 0.4 })];
  const series = (group: CitedGroup) => points.filter((p) => p.group === group);
  for (const group of DRAW_ORDER) {
    marks.push(Plot.line(series(group), { x: "year", y: "median", stroke: GROUP_COLORS[group], strokeWidth: 2.25, strokeDasharray: DASH[group] }));
  }
  for (const group of DRAW_ORDER) {
    marks.push(
      Plot.dot(series(group), {
        x: "year",
        y: "median",
        stroke: GROUP_COLORS[group],
        fill: COLORS.paper,
        strokeWidth: 1.75,
        r: MARKER_R[group],
        symbol: GROUP_SYMBOLS[group],
      }),
    );
  }
  for (const group of CITED_GROUPS) {
    marks.push(
      Plot.text(
        series(group).filter((p) => p.year === lastYear),
        { x: "year", y: "median", text: () => GROUP_LABELS[group], fill: GROUP_COLORS[group], dx: 10, dy: offsets[group] * LABEL_STEP, textAnchor: "start", fontWeight: 600 },
      ),
    );
  }
  const final = points.filter((p) => p.year === lastYear);
  if (final.every((p) => p.median === final[0]!.median)) {
    // One shared endpoint: say so above the stacked labels, with a bracket tying them to it.
    const top = Math.min(...Object.values(offsets)) * LABEL_STEP;
    const bottom = Math.max(...Object.values(offsets)) * LABEL_STEP;
    marks.push(
      Plot.text([final[0]!], { x: "year", y: "median", text: (p: Q2Point) => `All: ${p.median} years`, fill: "currentColor", dx: 10, dy: top - LABEL_STEP - 2, textAnchor: "start", fontSize: 11 }),
      Plot.text([final[0]!], { x: "year", y: "median", text: () => "[", fill: "currentColor", fillOpacity: 0.6, dx: 4, dy: 0, fontSize: bottom - top + LABEL_STEP, fontWeight: 300 }),
    );
  }
  const years = [...new Set(points.map((p) => p.year))].map((year) => ({
    year,
    median: Math.max(...points.filter((p) => p.year === year).map((p) => p.median)),
    title: [
      `Citation year ${year}`,
      ...CITED_GROUPS.map((g) => `${GROUP_LABELS[g]}: ${points.find((p) => p.year === year && p.group === g)!.median} years`),
    ].join("\n"),
  }));
  marks.push(Plot.tip(years, Plot.pointerX({ x: "year", y: "median", title: "title" })));
  return Plot.plot({
    width,
    height,
    marginLeft: MARGIN_LEFT,
    marginRight: MARGIN_RIGHT,
    marginTop: 24,
    style: { fontFamily: "inherit", fontSize: "13px", fontVariantNumeric: "tabular-nums", background: "transparent" },
    x: { label: null, tickFormat: "d", ticks: yearTicks(points, width - MARGIN_LEFT - MARGIN_RIGHT) },
    y: { label: "Median age of cited work (years)", domain: [0, 10], grid: true, ticks: 5 },
    marks,
  });
}

export function mountQ2(container: HTMLElement, points: Q2Point[]): void {
  mountChart(container, (width, height) => render(points, width, height));
}
