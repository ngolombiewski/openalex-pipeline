# ADR 001 — AI Topic Classification Rule

**Status:** Accepted

## Context

The three analytical questions all require classifying each work as AI or non-AI. OpenAlex assigns each work a ranked list of topics; the top-ranked entry is `primary_topic`. We needed a rule that is simple, analytically defensible, and avoids double-counting.

The boundary case is Computer Vision and Pattern Recognition (CV/PR), which straddles AI and non-AI depending on the paper. Its inclusion changes headline numbers for all three questions.

## Decision

A work is classified as AI if its `primary_topic.subfield.id` matches one of a defined set of AI subfields. Classification uses `primary_topic` exclusively; the full `topics` array is retained in bronze but plays no role in classification.

Two ablation variants are defined and both are computed for all analytical questions:

| Variant | Subfields |
|---|---|
| `ai_strict` | Artificial Intelligence only |
| `ai_broad` | Artificial Intelligence + Computer Vision and Pattern Recognition |

## Rationale

`primary_topic` reflects a work's core contribution as judged by OpenAlex's model. Using it avoids double-counting (a work with three AI-adjacent topics would be counted once, not three times) and is the most analytically defensible choice — we trust OpenAlex's ranking rather than re-weighting it.

The ablation approach handles CV/PR ambiguity explicitly rather than making a hidden all-or-nothing choice. Reporting both variants makes the sensitivity of the results visible.

## Alternatives considered

**Use any topic in the `topics` array:** A work would be classified AI if any of its topics matched, regardless of rank. Rejected — causes double-counting and inflates AI share. A paper that is primarily about distributed systems but cites one ML technique would be counted as AI.

**Weight by topic score:** Compute a continuous AI-ness score using topic scores from the `topics` array. Rejected — adds complexity without a clear analytical benefit for the questions being asked, and the score semantics are not well-documented.

**Exclude CV/PR entirely (ai_strict only):** Simpler, but buries a real methodological choice. The ablation approach makes the sensitivity explicit at almost no additional cost.
