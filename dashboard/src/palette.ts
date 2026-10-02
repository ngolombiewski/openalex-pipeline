/**
 * Series colours, shared by CSS (as custom properties) and charts.
 *
 * AI, CV/PR, and rest of CS keep their colours across sections. Q1's AI + CV/PR
 * is a combined definition (AI + CV/PR) and gets its own colour, never CV/PR's.
 */
export const COLORS = {
  ai: "#c2410c",
  broadAi: "#7c2d12",
  cvPr: "#1d6fa5",
  restCs: "#4d7c0f",
  neutral: "#6b7280",
  paper: "#fbfaf7",
  ink: "#1c1b19",
} as const;
