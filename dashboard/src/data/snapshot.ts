/**
 * The frozen snapshot boundary.
 *
 * `parseSnapshot` is the only way snapshot data enters the site. It checks the
 * file boundary — required files, row shapes and types, nonempty relations,
 * recorded row counts and bounds, unique grain keys, and the rows the fixed
 * views need —
 * and returns typed rows. It does not re-check gold's analytical invariants.
 *
 * Column lists and nullability mirror the enforced gold contracts and the
 * exporter's pinned columns (tools/export_dashboard_snapshot.py).
 */

export class SnapshotDataError extends Error {
  readonly file: string;

  constructor(file: string, problem: string) {
    super(`${file}: ${problem}`);
    this.name = "SnapshotDataError";
    this.file = file;
  }
}

export const VARIANTS = ["strict", "broad"] as const;
export const CITED_GROUPS = ["ai", "cv_pr", "rest_cs"] as const;
export const UNCLASSIFIED_SUBFIELD_ID = "__unclassified__";

/** Fixed analytical views of this release. */
export const Q1_FIRST_YEAR = 1980;
export const Q3_COHORT = 2020;
export const Q3_WINDOW = 5;
/** Subfields the Q3 chart labels directly; each must be present in the cell. */
export const Q3_LABELLED_SUBFIELD_IDS = [
  "https://openalex.org/subfields/1702",
  "https://openalex.org/subfields/1707",
  "https://openalex.org/subfields/1704",
  "https://openalex.org/subfields/1710",
] as const;

export type Variant = (typeof VARIANTS)[number];
export type CitedGroup = (typeof CITED_GROUPS)[number];

export interface AiShareRow {
  publication_year: number;
  variant: Variant;
  cs_works: number;
  ai_works: number;
  share: number;
  is_partial_year: boolean;
}

export interface CitationAgeRow {
  citation_year: number;
  cited_group: CitedGroup;
  citation_events: number;
  cited_works: number;
  p25_citation_age: number;
  median_citation_age: number;
  p75_citation_age: number;
  share_age_lte_2: number;
  share_age_lte_5: number;
  share_age_lte_10: number;
}

/** Concentration measures; nulls mean undefined (zero citations), not zero. */
interface GiniMeasures {
  citation_age: number;
  n_papers: number;
  total_citations: number;
  zero_share: number;
  gini: number | null;
  gini_cited_only: number | null;
  top1_share: number | null;
  top5_share: number | null;
  top10_share: number | null;
  age0_citation_share: number | null;
  zero_share_including_age0: number;
}

export interface GiniSubfieldRow extends GiniMeasures {
  publication_year: number;
  subfield_id: string;
  subfield_display_name: string;
  is_ai_strict: boolean;
  is_ai_broad: boolean;
}

export interface GiniGroupRow extends GiniMeasures {
  publication_year: number;
  cited_group: CitedGroup;
}

export interface SnapshotBounds {
  year_min: number;
  year_max: number;
  partial_year: number;
  citation_age_year_min: number;
  citation_age_year_max: number;
  gini_cohort_min: number;
  gini_citation_year_max: number;
}

export interface SnapshotMeta {
  exported_at: string;
  source_tables: Record<RelationName, string>;
  source_modified_at: Record<RelationName, string>;
  pipeline_revision: string;
  bounds: SnapshotBounds;
  row_counts: Record<RelationName, number>;
}

export interface Snapshot {
  meta: SnapshotMeta;
  aiShare: AiShareRow[];
  citationAge: CitationAgeRow[];
  giniBySubfield: GiniSubfieldRow[];
  giniByGroup: GiniGroupRow[];
}

export const RELATION_NAMES = [
  "gold_ai_share_by_year",
  "gold_citation_age_by_year",
  "gold_citation_gini_by_subfield",
  "gold_citation_gini_by_group",
] as const;
export type RelationName = (typeof RELATION_NAMES)[number];

/** Raw parsed JSON, keyed by snapshot filename. */
export type RawSnapshotFiles = Record<string, unknown>;

type Kind = "int" | "float" | "string" | "bool";
type ColumnSpec = Record<string, { kind: Kind; nullable?: true; values?: readonly string[] }>;

const GINI_COLUMNS: ColumnSpec = {
  citation_age: { kind: "int" },
  n_papers: { kind: "int" },
  total_citations: { kind: "int" },
  zero_share: { kind: "float" },
  gini: { kind: "float", nullable: true },
  gini_cited_only: { kind: "float", nullable: true },
  top1_share: { kind: "float", nullable: true },
  top5_share: { kind: "float", nullable: true },
  top10_share: { kind: "float", nullable: true },
  age0_citation_share: { kind: "float", nullable: true },
  zero_share_including_age0: { kind: "float" },
};

const COLUMNS: Record<RelationName, ColumnSpec> = {
  gold_ai_share_by_year: {
    publication_year: { kind: "int" },
    variant: { kind: "string", values: VARIANTS },
    cs_works: { kind: "int" },
    ai_works: { kind: "int" },
    share: { kind: "float" },
    is_partial_year: { kind: "bool" },
  },
  gold_citation_age_by_year: {
    citation_year: { kind: "int" },
    cited_group: { kind: "string", values: CITED_GROUPS },
    citation_events: { kind: "int" },
    cited_works: { kind: "int" },
    p25_citation_age: { kind: "int" },
    median_citation_age: { kind: "int" },
    p75_citation_age: { kind: "int" },
    share_age_lte_2: { kind: "float" },
    share_age_lte_5: { kind: "float" },
    share_age_lte_10: { kind: "float" },
  },
  gold_citation_gini_by_subfield: {
    publication_year: { kind: "int" },
    subfield_id: { kind: "string" },
    subfield_display_name: { kind: "string" },
    is_ai_strict: { kind: "bool" },
    is_ai_broad: { kind: "bool" },
    ...GINI_COLUMNS,
  },
  gold_citation_gini_by_group: {
    publication_year: { kind: "int" },
    cited_group: { kind: "string", values: CITED_GROUPS },
    ...GINI_COLUMNS,
  },
};

const GRAIN: Record<RelationName, readonly string[]> = {
  gold_ai_share_by_year: ["publication_year", "variant"],
  gold_citation_age_by_year: ["citation_year", "cited_group"],
  gold_citation_gini_by_subfield: ["publication_year", "subfield_id", "citation_age"],
  gold_citation_gini_by_group: ["publication_year", "cited_group", "citation_age"],
};

const BOUND_KEYS: readonly (keyof SnapshotBounds)[] = [
  "year_min",
  "year_max",
  "partial_year",
  "citation_age_year_min",
  "citation_age_year_max",
  "gini_cohort_min",
  "gini_citation_year_max",
];

const META_FILE = "snapshot.json";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasKind(value: unknown, kind: Kind): boolean {
  switch (kind) {
    case "int":
      return Number.isSafeInteger(value);
    case "float":
      return typeof value === "number" && Number.isFinite(value);
    case "string":
      return typeof value === "string";
    case "bool":
      return typeof value === "boolean";
  }
}

function sameKeys(actual: string[], expected: readonly string[]): boolean {
  return actual.length === expected.length && expected.every((key) => actual.includes(key));
}

function parseRows(relation: RelationName, raw: unknown): Record<string, unknown>[] {
  const file = `${relation}.json`;
  if (raw === undefined) throw new SnapshotDataError(file, "file is missing");
  if (!Array.isArray(raw)) throw new SnapshotDataError(file, "expected an array of rows");
  if (raw.length === 0) throw new SnapshotDataError(file, "relation is empty");

  const spec = COLUMNS[relation];
  const columns = Object.keys(spec);
  const seen = new Set<string>();
  raw.forEach((row: unknown, index) => {
    if (!isRecord(row)) throw new SnapshotDataError(file, `row ${index} is not an object`);
    if (!sameKeys(Object.keys(row), columns)) {
      throw new SnapshotDataError(
        file,
        `row ${index} columns [${Object.keys(row).join(", ")}] != pinned [${columns.join(", ")}]`,
      );
    }
    for (const [column, { kind, nullable, values }] of Object.entries(spec)) {
      const value = row[column];
      if (value === null) {
        if (nullable) continue;
        throw new SnapshotDataError(file, `row ${index} ${column} is null`);
      }
      if (!hasKind(value, kind)) {
        throw new SnapshotDataError(file, `row ${index} ${column}=${JSON.stringify(value)} is not ${kind}`);
      }
      if (values && !values.includes(value as string)) {
        throw new SnapshotDataError(file, `row ${index} ${column}=${JSON.stringify(value)} is not one of ${values.join(", ")}`);
      }
    }
    const key = GRAIN[relation].map((column) => String(row[column])).join(" × ");
    if (seen.has(key)) throw new SnapshotDataError(file, `duplicate grain key ${key}`);
    seen.add(key);
  });
  return raw;
}

function parseMeta(raw: unknown): SnapshotMeta {
  const fail = (problem: string): never => {
    throw new SnapshotDataError(META_FILE, problem);
  };
  if (raw === undefined) fail("file is missing");
  if (!isRecord(raw)) return fail("expected an object");

  if (typeof raw.exported_at !== "string" || Number.isNaN(Date.parse(raw.exported_at))) {
    fail("exported_at is not a timestamp");
  }
  if (typeof raw.pipeline_revision !== "string" || raw.pipeline_revision === "") {
    fail("pipeline_revision is empty");
  }
  for (const field of ["source_tables", "source_modified_at", "row_counts"] as const) {
    const value = raw[field];
    if (!isRecord(value) || !sameKeys(Object.keys(value), RELATION_NAMES)) {
      fail(`${field} must name exactly the four relations`);
    }
    const kind: Kind = field === "row_counts" ? "int" : "string";
    for (const relation of RELATION_NAMES) {
      if (!hasKind((value as Record<string, unknown>)[relation], kind)) {
        fail(`${field}.${relation} is not ${kind}`);
      }
    }
  }
  const bounds = raw.bounds;
  if (!isRecord(bounds) || !sameKeys(Object.keys(bounds), BOUND_KEYS)) {
    fail(`bounds must name exactly ${BOUND_KEYS.join(", ")}`);
  }
  for (const key of BOUND_KEYS) {
    if (!hasKind((bounds as Record<string, unknown>)[key], "int")) fail(`bounds.${key} is not int`);
  }
  return raw as unknown as SnapshotMeta;
}

/**
 * Validate raw snapshot files and return typed relations.
 *
 * Throws `SnapshotDataError` naming the file and problem for: a missing file,
 * a non-array relation or empty relation, a row whose columns differ from the
 * pinned list, a value of the wrong type or a null in a non-nullable column, an
 * unknown variant or cited group, a duplicate grain key, malformed
 * `snapshot.json`, a recorded row count that differs from the file, a recorded
 * bound that differs from its relation's extent (see `checkBounds`), a
 * partial-year flag that disagrees with the recorded partial year on any row,
 * or a row the fixed views need being absent. Other errors propagate.
 */
export function parseSnapshot(files: RawSnapshotFiles): Snapshot {
  const meta = parseMeta(files[META_FILE]);
  const rows = Object.fromEntries(
    RELATION_NAMES.map((relation) => [relation, parseRows(relation, files[`${relation}.json`])]),
  ) as Record<RelationName, Record<string, unknown>[]>;
  for (const relation of RELATION_NAMES) {
    if (rows[relation].length !== meta.row_counts[relation]) {
      throw new SnapshotDataError(
        `${relation}.json`,
        `${rows[relation].length} rows != recorded ${meta.row_counts[relation]}`,
      );
    }
  }
  const snapshot: Snapshot = {
    meta,
    aiShare: rows.gold_ai_share_by_year as unknown as AiShareRow[],
    citationAge: rows.gold_citation_age_by_year as unknown as CitationAgeRow[],
    giniBySubfield: rows.gold_citation_gini_by_subfield as unknown as GiniSubfieldRow[],
    giniByGroup: rows.gold_citation_gini_by_group as unknown as GiniGroupRow[],
  };
  checkBounds(snapshot);
  selectQ1(snapshot);
  selectQ2(snapshot);
  selectQ3(snapshot);
  return snapshot;
}

/**
 * Reconcile `meta.bounds` with the data, as the exporter did against dbt:
 * Q1 publication years span exactly `year_min..year_max` and each row is
 * flagged partial exactly when its year is `partial_year`; Q2 citation years
 * span exactly `citation_age_year_min..citation_age_year_max`; both Q3
 * relations span cohorts `gini_cohort_min..gini_citation_year_max - 1` and
 * reach exactly `gini_citation_year_max` as their last citation year.
 */
function checkBounds(snapshot: Snapshot): void {
  const bounds = snapshot.meta.bounds;
  const span = (file: string, what: string, values: number[], min: number, max: number): void => {
    const actual = [Math.min(...values), Math.max(...values)];
    if (actual[0] !== min || actual[1] !== max) {
      throw new SnapshotDataError(file, `${what} ${actual.join("..")} != recorded ${min}..${max}`);
    }
  };

  const q1File = "gold_ai_share_by_year.json";
  span(q1File, "publication years", snapshot.aiShare.map((r) => r.publication_year), bounds.year_min, bounds.year_max);
  const misflagged = snapshot.aiShare.filter(
    (r) => r.is_partial_year !== (r.publication_year === bounds.partial_year),
  );
  if (misflagged.length > 0) {
    const rows = misflagged.map((r) => `${r.publication_year} × ${r.variant}`).join(", ");
    throw new SnapshotDataError(q1File, `partial-year flag disagrees with ${bounds.partial_year} on ${rows}`);
  }

  span(
    "gold_citation_age_by_year.json",
    "citation years",
    snapshot.citationAge.map((r) => r.citation_year),
    bounds.citation_age_year_min,
    bounds.citation_age_year_max,
  );

  const gini: [string, (GiniSubfieldRow | GiniGroupRow)[]][] = [
    ["gold_citation_gini_by_subfield.json", snapshot.giniBySubfield],
    ["gold_citation_gini_by_group.json", snapshot.giniByGroup],
  ];
  for (const [file, relation] of gini) {
    const cohorts = relation.map((r) => r.publication_year);
    span(file, "cohorts", cohorts, bounds.gini_cohort_min, bounds.gini_citation_year_max - 1);
    const last = Math.max(...relation.map((r) => r.publication_year + r.citation_age));
    if (last !== bounds.gini_citation_year_max) {
      throw new SnapshotDataError(file, `last citation year ${last} != recorded ${bounds.gini_citation_year_max}`);
    }
  }
}

/**
 * Q1 view: both variants for every year from `Q1_FIRST_YEAR` through
 * `year_max`, ordered by year then variant. The partial year must be
 * `year_max`, because the chart dashes the final segment.
 */
export function selectQ1(snapshot: Snapshot): AiShareRow[] {
  const file = "gold_ai_share_by_year.json";
  const { year_max, partial_year } = snapshot.meta.bounds;
  if (partial_year !== year_max) {
    throw new SnapshotDataError(META_FILE, `partial year ${partial_year} is not the last year ${year_max}`);
  }
  const view: AiShareRow[] = [];
  for (let year = Q1_FIRST_YEAR; year <= year_max; year++) {
    for (const variant of VARIANTS) {
      const row = snapshot.aiShare.find((r) => r.publication_year === year && r.variant === variant);
      if (!row) throw new SnapshotDataError(file, `missing ${year} × ${variant}`);
      view.push(row);
    }
  }
  return view;
}

/** Q2 view: every cited group for every citation year in bounds, ordered by year then group. */
export function selectQ2(snapshot: Snapshot): CitationAgeRow[] {
  const file = "gold_citation_age_by_year.json";
  const { citation_age_year_min, citation_age_year_max } = snapshot.meta.bounds;
  const view: CitationAgeRow[] = [];
  for (let year = citation_age_year_min; year <= citation_age_year_max; year++) {
    for (const group of CITED_GROUPS) {
      const row = snapshot.citationAge.find((r) => r.citation_year === year && r.cited_group === group);
      if (!row) throw new SnapshotDataError(file, `missing ${year} × ${group}`);
      view.push(row);
    }
  }
  return view;
}

/**
 * Q3 view: classified subfields in the fixed cell (`Q3_COHORT`, cumulative
 * window `Q3_WINDOW`), in file order. The window must lie within the snapshot's
 * citation years, and every classified subfield occurring anywhere in the
 * relation must be present, labelled ones included. Rows with null
 * measures are kept; omitting them from the chart is a presentation decision.
 */
export function selectQ3(snapshot: Snapshot): GiniSubfieldRow[] {
  const file = "gold_citation_gini_by_subfield.json";
  const { gini_citation_year_max } = snapshot.meta.bounds;
  if (Q3_COHORT + Q3_WINDOW > gini_citation_year_max) {
    throw new SnapshotDataError(
      META_FILE,
      `cell ${Q3_COHORT}/${Q3_WINDOW} ends after citation year ${gini_citation_year_max}`,
    );
  }
  const view = snapshot.giniBySubfield.filter(
    (row) =>
      row.publication_year === Q3_COHORT &&
      row.citation_age === Q3_WINDOW &&
      row.subfield_id !== UNCLASSIFIED_SUBFIELD_ID,
  );
  const classified = new Set(
    snapshot.giniBySubfield.map((row) => row.subfield_id).filter((id) => id !== UNCLASSIFIED_SUBFIELD_ID),
  );
  for (const id of [...Q3_LABELLED_SUBFIELD_IDS, ...classified]) {
    if (!view.some((row) => row.subfield_id === id)) {
      throw new SnapshotDataError(file, `cell ${Q3_COHORT}/${Q3_WINDOW} is missing ${id}`);
    }
  }
  return view;
}
