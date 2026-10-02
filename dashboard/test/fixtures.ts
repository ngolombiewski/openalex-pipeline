import aiShare from "../data/gold_ai_share_by_year.json" with { type: "json" };
import citationAge from "../data/gold_citation_age_by_year.json" with { type: "json" };
import giniByGroup from "../data/gold_citation_gini_by_group.json" with { type: "json" };
import giniBySubfield from "../data/gold_citation_gini_by_subfield.json" with { type: "json" };
import meta from "../data/snapshot.json" with { type: "json" };
import { parseSnapshot, type Snapshot } from "../src/data/snapshot.ts";

/** A freshly parsed copy of the committed snapshot, safe to mutate per test. */
export function committedSnapshot(): Snapshot {
  return parseSnapshot(
    structuredClone({
      "snapshot.json": meta,
      "gold_ai_share_by_year.json": aiShare,
      "gold_citation_age_by_year.json": citationAge,
      "gold_citation_gini_by_subfield.json": giniBySubfield,
      "gold_citation_gini_by_group.json": giniByGroup,
    }),
  );
}
