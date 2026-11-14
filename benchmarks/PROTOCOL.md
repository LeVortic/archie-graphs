# Draft evaluation protocol

Primary focus: factual correctness on multi-hop C# architecture questions. This protocol is proposed and needs review before a research run.

## Primary comparison

Compare source and graph modes on the same reviewed questions with dependency_depth >= 2, the same source snapshot, language/embedding model identities, generation settings, and total context ceiling. Counterbalance which mode runs first and shuffle question order using a recorded seed. Record actual context tokens, generation latency, and full pipeline latency; equal ceilings do not guarantee equal actual token usage.

The proposed primary outcome is macro-average atomic-fact F1 per question on the multi-hop subset. Report its precision and recall components too. The current five multi-hop calibration questions are too few and too development-exposed for general research conclusions. Build a separately reviewed held-out set before formal testing. Control questions cover local facts, direct/reverse dependencies, unresolved identifiers, and insufficient evidence.

## Human fact grading

1. Review the expected facts and acceptable source regions before examining model answers. Labels must be necessary to answer the question, atomic, non-duplicated, and source-backed. Runtime caveats must not become mandatory gold facts unless asked.
2. Hide answer mode and counterbalance presentation when collecting human judgments. The generated review template is a data-entry scaffold, not a blinded-review implementation.
3. Split generated claims into atomic factual propositions when a claim contains multiple assertions. Match propositions to gold fact IDs by meaning, not keywords. Count a gold fact as recovered at most once.
4. Record incorrect factual propositions and unsupported propositions separately. A fact absent from the gold list is not automatically false: review whether it is correct, relevant, and supported before scoring it. Unexpected valid facts may reveal an incomplete rubric; resolve rubric defects consistently across both modes before analysis.
5. Compute fact precision, recall, and F1 only after these rules and edge cases are approved and labels completed. The current runner deliberately computes none of those quality scores.
6. Keep abstention cases separate from ordinary fact F1 until a scoring policy is approved. An abstention on an answerable question loses coverage; an abstention on an unanswerable question can be correct. A failure, timeout, or malformed response is not an abstention and must remain visible.

## Secondary outcomes

Human-assessed unsupported architectural claims, valid/relevant source support, correct abstention, failure rates, token use, and latency are secondary. Structural citation validity is an infrastructure check only. Model support_status=uncertain is not a human annotation.

## Required before research claims

- Confirm research-question wording, primary metric, atomic-fact rules, abstention policy, and failure/exclusion policy.
- Independently review labels, dependency-depth categories, and source regions; record reviewer/date.
- Expand and freeze a held-out set; avoid tuning retrieval, graph selection, or prompts against it.
- Record source/benchmark versions, software/model identities, hardware, seed, and all raw attempts.
- Plan paired uncertainty estimates and repository/topic clustering; do not treat overlapping questions or shared graph edges as independent evidence.

Both development benchmark JSON files record label approval by Victor on 2026-11-10. Rosa completed qualitative answer review on 2026-11-11; see [answer review](ANSWER_REVIEW.md). These approvals do not establish formal scoring-protocol approval, blinded grading, or held-out validity. Atomic fact grading remains pending. --allow-draft remains available only for unapproved development benchmarks.
