/**
 * The committed snapshot, validated once at build time.
 *
 * Imported only from page frontmatter, so the raw relations stay out of the
 * client bundle. A snapshot error fails the build.
 *
 * The files are static imports, so a missing file or invalid JSON fails the
 * build as a bundler error before `parseSnapshot` runs, not as a
 * `SnapshotDataError`. Everything after parsing is `parseSnapshot`'s contract.
 */
import aiShare from "../../data/gold_ai_share_by_year.json" with { type: "json" };
import citationAge from "../../data/gold_citation_age_by_year.json" with { type: "json" };
import giniByGroup from "../../data/gold_citation_gini_by_group.json" with { type: "json" };
import giniBySubfield from "../../data/gold_citation_gini_by_subfield.json" with { type: "json" };
import meta from "../../data/snapshot.json" with { type: "json" };
import { parseSnapshot } from "./snapshot.ts";

export const snapshot = parseSnapshot({
  "snapshot.json": meta,
  "gold_ai_share_by_year.json": aiShare,
  "gold_citation_age_by_year.json": citationAge,
  "gold_citation_gini_by_subfield.json": giniBySubfield,
  "gold_citation_gini_by_group.json": giniByGroup,
});
