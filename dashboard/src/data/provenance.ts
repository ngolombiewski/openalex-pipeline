/**
 * Provenance as Methods renders it.
 *
 * `parseSnapshot` checks provenance fields for presence and type only. Before
 * Methods renders them, `provenance` checks their meaning: `exported_at` is a
 * UTC timestamp, and every source table is a fully qualified production
 * `openalex_analytics` table named after its relation. It throws
 * `SnapshotDataError` on `snapshot.json` otherwise.
 */
import { RELATION_NAMES, SnapshotDataError, type RelationName, type SnapshotMeta } from "./snapshot.ts";

const META_FILE = "snapshot.json";
const UTC_TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/;
const PROJECT_ID = "[a-z][a-z0-9-]{4,28}[a-z0-9]";
export const UNKNOWN_REVISION = "unknown";

export interface Provenance {
  /** Export time, e.g. "1 October 2026, 10:46 UTC". */
  exportedAt: string;
  /** ISO export timestamp for `<time datetime>`. */
  exportedAtIso: string;
  /** The recorded revision, or "not recorded" for `unknown`. */
  pipelineRevision: string;
  sourceTables: { relation: RelationName; table: string; rows: number }[];
}

export function provenance(meta: SnapshotMeta): Provenance {
  if (!UTC_TIMESTAMP.test(meta.exported_at)) {
    throw new SnapshotDataError(META_FILE, `exported_at ${meta.exported_at} is not a UTC timestamp`);
  }
  const sourceTables = RELATION_NAMES.map((relation) => {
    const table = meta.source_tables[relation];
    if (!new RegExp(`^${PROJECT_ID}\\.openalex_analytics\\.${relation}$`).test(table)) {
      throw new SnapshotDataError(
        META_FILE,
        `source_tables.${relation}=${table} is not a production openalex_analytics.${relation} table`,
      );
    }
    return { relation, table, rows: meta.row_counts[relation] };
  });
  const exported = new Date(meta.exported_at);
  const date = exported.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
  const time = exported.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
  return {
    exportedAt: `${date}, ${time} UTC`,
    exportedAtIso: meta.exported_at,
    pipelineRevision: meta.pipeline_revision === UNKNOWN_REVISION ? "not recorded" : meta.pipeline_revision,
    sourceTables,
  };
}
