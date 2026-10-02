/**
 * Display identity of the three cited-work groups, shared by Q2 and Q3.
 * Each keeps one colour and one marker shape across sections.
 */
import type { CitedGroup } from "../data/snapshot.ts";
import { COLORS } from "../palette.ts";

export const GROUP_LABELS: Record<CitedGroup, string> = {
  ai: "AI",
  cv_pr: "CV/PR",
  rest_cs: "Rest of CS",
};

export const GROUP_COLORS: Record<CitedGroup, string> = {
  ai: COLORS.ai,
  cv_pr: COLORS.cvPr,
  rest_cs: COLORS.restCs,
};

export const GROUP_SYMBOLS: Record<CitedGroup, "square" | "triangle" | "circle"> = {
  ai: "square",
  cv_pr: "triangle",
  rest_cs: "circle",
};
