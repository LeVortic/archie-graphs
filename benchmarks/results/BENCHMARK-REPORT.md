# Benchmark report: source vs graph answering with Claude Sonnet 5.5

Author and reviewer: Rosa Cortes · Date: 14 November 2026 · Benchmarks: `fixture-v1.json` (11 questions), `markovjunior-v1.json` (18 questions)

## Summary

- **Both runs completed with no failures**: 22/22 fixture answers and 36/36 MarkovJunior answers, and every structural citation check passed.
- **Neither mode produced an incorrect or unsupported claim** after blind human grading. Precision is 1.00 in both modes on both benchmarks.
- **On the fixture the two modes cannot be told apart.** Both score F1 = 1.00 and abstain correctly on all three unanswerable questions.
- **On MarkovJunior the graph mode answered more questions.** It abstained on 3 of 16 answerable questions; source mode abstained on 7. Counting an abstention as F1 = 0, macro F1 is **0.71 in graph mode and 0.52 in source mode**. Graph mode was better on 4 questions, source mode on 1, and 11 were ties.
- **When both modes answered, quality was the same.** On the 9 questions both modes answered, 8 were ties and source mode was better on 1 (`markov-cycle`). The graph benefit seen here is coverage, not answer quality.
- **The graph benefit costs context.** Graph mode used about twice the context (3,773 vs 1,928 Qwen tokens per answer), took about 3 s longer per answer end to end, and cost about 66% more in equivalent API cost.
- **Most remaining errors are retrieval misses.** Three answerable MarkovJunior questions were abstained on in both modes because the lines that hold the answer were never retrieved.
- **Earlier Qwen3-4B runs got identical evidence.** On those runs, Qwen made one unsupported claim and gave more partial answers. Clean precision is partly a property of Claude ([comparison](#qualitative-comparison-with-the-earlier-qwen3-4b-runs)).
- **These are development results, not research evidence.** The sample is small and comes from one reviewer and one model run. The answering model was Claude, not the project's Qwen3-4B. Victor's questions were used during development. See [Limitations](#limitations).

## Scope

This report covers the paired source/graph evaluation of the two approved development benchmarks after a second reviewer added 13 questions. The additions were 3 for the fixture and 10 for MarkovJunior; their IDs contain `-rc-`. It follows `benchmarks/PROTOCOL.md` as far as a development run allows:

- grading was blind;
- precision, recall and F1 come only from human labels;
- abstentions are reported separately;
- failures stay visible;
- the raw run records are kept unchanged.

The earlier 8-question fixture run (`fixture-claude-sonnet/`) is kept for traceability. The 11-question run in `fixture-full-claude-sonnet/` supersedes it.

## Setup

| Item | Fixture | MarkovJunior |
| --- | --- | --- |
| Run | `run:e2c85938820f45d79dd74885184fd337` | `run:9c49bc6497544c39a308347fc6f46454` |
| Benchmark hash | `sha256:89c467fe…` | `sha256:29dc8827…` |
| Source snapshot | `sha256:450aba2d…` | `sha256:b2534eee…` |
| Index | `index:36eb67de…` | `index:99e56807…` |
| Retrieval top-k | 5 | 8 |
| Questions (answerable + abstain) | 11 (8 + 3) | 18 (16 + 2) |

Settings shared by both runs:

| Setting | Value |
| --- | --- |
| Seed | 42 |
| Modes | `source` and `graph`, counterbalanced and shuffled by the runner |
| Context budget | 4,096 tokens, counted with the pinned Qwen3 tokenizer |
| Answering model | Claude Sonnet 5.5 (`claude-sonnet-5-5`) through the Claude Code CLI 2.1.325; revision unpinned |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` @ `1110a243`, CPU |
| Graph limits | 5 seeds, depth 2, 20 paths |
| Machine | macOS, Intel x86_64, no GPU; Python 3.12.10, torch 2.2.2, transformers 4.57.6, sentence-transformers 5.7.0 |

**Why Claude.** Qwen3-4B is not practical on an Intel Mac without a GPU. As agreed with the team, a local adapter swapped Qwen for Claude and is kept outside the repository. The adapter keeps the project's prompt, evidence selection, JSON schema, citation checks and answer validation unchanged.

Claude ran with no tools, no session persistence and an empty working directory, so it saw only the supplied excerpts. **These results must not be pooled with Qwen results.**

## Grading method

All 58 answers were graded blind in a review page. Each question showed its two answers as "A" and "B", in an order fixed by a hash of the run ID and question ID; the mode stayed hidden. For each answer:

- each claim was labelled `ok` (correct and asked), `extra` (correct but not asked), `incorrect`, or `unsupported` (the cited evidence does not support it);
- each expected fact was marked as recovered or not, by meaning;
- unanswerable questions were marked as correct or incorrect abstention.

After grading, the labels were checked against the source for consistency. This check found **12 changes in 7 answers**; the reviewer corrected them before any score was computed:

- 5 expected facts that the answer did state in other words;
- 5 claims labelled `unsupported` or `incorrect` that the cited lines do support;
- 2 claims relabelled from `extra` to `ok`.

Notes on two abstentions were also rewritten to record their cause as a retrieval miss. This check was not blind to mode. Every change is in the final `review.json`.

Metrics are computed by `archie analyze`, which is new in this branch:

- **Precision**: correct claims (`ok` + `extra`) divided by all claims in an answer.
- **Recall**: recovered facts divided by expected facts.
- **F1**: harmonic mean of precision and recall, per question, then macro-averaged.

On answerable questions, an abstention has no precision. The analysis therefore reports two views:

- **F1 (answered only)**: abstentions excluded.
- **F1 (abstain = 0)**: an abstention counts as F1 = 0, which reflects coverage.

Claims are scored as the model produced them. They are not split further into atomic propositions.

## Results

### Fixture (11 questions)

| Mode | Failed | Answered / answerable | Precision | Recall | F1 | Correct abstentions | Incorrect / unsupported claims |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `source` | 0 | 8/8 | 1.00 | 1.00 | **1.00** | 3/3 | 0 / 0 |
| `graph` | 0 | 8/8 | 1.00 | 1.00 | **1.00** | 3/3 | 0 / 0 |

Every paired comparison is a tie (8/8). The fixture checks the workflow; it cannot measure a graph benefit.

### MarkovJunior (18 questions)

| Mode | Failed | Answered / answerable | Precision (answered) | Recall (answered) | F1 (answered) | Recall (all answerable) | **F1 (abstain = 0)** | Correct abstentions | Incorrect / unsupported claims |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `source` | 0 | 9/16 | 1.00 | 0.89 | 0.92 | 0.50 | **0.52** | 2/2 | 0 / 0 |
| `graph` | 0 | 13/16 | 1.00 | 0.82 | 0.87 | 0.67 | **0.71** | 2/2 | 0 / 0 |

Paired per-question F1, graph minus source:

| Comparison | Pairs | Mean difference | Graph better | Source better | Ties |
| --- | ---: | ---: | ---: | ---: | ---: |
| Abstain = 0, all answerable | 16 | +0.19 | 4 | 1 | 11 |
| Both modes answered | 9 | −0.03 | 0 | 1 | 8 |

#### By dependency depth (F1, abstain = 0)

| Subset | Answerable | Source answered | Graph answered | Source F1 | Graph F1 | Graph / source better |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Depth 0 | 3 | 2 | 3 | 0.67 | 1.00 | 1 / 0 |
| Depth 1 | 7 | 4 | 6 | 0.57 | 0.76 | 2 / 0 |
| Depth 2 | 4 | 1 | 2 | 0.25 | 0.50 | 1 / 0 |
| Depth 3 | 2 | 2 | 2 | 0.65 | 0.50 | 0 / 1 |
| **Multi-hop (depth ≥ 2), primary subset** | 6 | 3 | 4 | 0.38 | 0.50 | 1 / 1 |

On the protocol's primary subset there are only 6 questions, and the result is one win each way.

#### By question author (F1, abstain = 0)

| Subset | Answerable | Source answered | Graph answered | Source F1 | Graph F1 | Graph / source better |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Victor's development questions | 7 | 6 | 7 | 0.83 | 0.93 | 1 / 1 |
| Second-reviewer questions (`-rc-`) | 9 | 3 | 6 | 0.28 | 0.54 | 3 / 0 |

The new questions were much harder for source mode. They had not been used during development, so this gap is one sign that the development questions may flatter the current retrieval setup.

#### Per question

| Question | Depth | Category | Source | Graph |
| --- | ---: | --- | --- | --- |
| `markov-grid` | 1 | dependency | 1.00 | 1.00 |
| `markov-inheritance` | 2 | path | 1.00 | 1.00 |
| `markov-initialization` | 0 | local_fact | 1.00 | 1.00 |
| `markov-loop` | 0 | local_fact | 1.00 | 1.00 |
| `markov-reverse` | 1 | reverse_dependency | 1.00 | 1.00 |
| `markov-static-path` | 2 | path | abstained | **1.00** |
| `markov-cycle` | 3 | cycle | **0.80** | 0.50 |
| `markov-insufficient` | 0 | insufficient_evidence | correct abstention | correct abstention |
| `markov-rc-rulenode-subclasses` | 1 | reverse_dependency | 1.00 | 1.00 |
| `markov-rc-search-caller` | 1 | reverse_dependency | 1.00 | 1.00 |
| `markov-rc-overlap-path` | 3 | path | 0.50 | 0.50 |
| `markov-rc-wfc-factory` | 0 | local_fact | abstained | **1.00** |
| `markov-rc-output` | 1 | dependency | abstained | **0.67** |
| `markov-rc-rulenode-loads` | 1 | dependency | abstained | **0.67** |
| `markov-rc-run-go-path` | 2 | path | abstained | abstained |
| `markov-rc-main-grid-path` | 2 | path | abstained | abstained |
| `markov-rc-branch-self` | 1 | cycle | abstained | abstained |
| `markov-rc-insufficient` | 0 | insufficient_evidence | correct abstention | correct abstention |

### Usage: source-only retrieval vs Archie graph evidence

The first table shows the mean per answer from the run records. Context is measured in Qwen3 tokens and selects the evidence. Pipeline latency covers retrieval, graph building and generation.

| Benchmark | Mode | Context sent | Generation latency | Pipeline latency |
| --- | --- | ---: | ---: | ---: |
| Fixture | `source` | 473 | 6.0 s | 6.2 s |
| Fixture | `graph` | 1,539 | 6.2 s | 6.7 s |
| MarkovJunior | `source` | 1,928 | 7.3 s | 12.0 s |
| MarkovJunior | `graph` | 3,773 | 7.8 s | 15.1 s |

The second table shows Claude's own counts from `claude-usage.jsonl`:

| Benchmark | Mode | Claude input tokens per answer | Claude output tokens per answer | Equivalent API cost (whole run) |
| --- | --- | ---: | ---: | ---: |
| Fixture | `source` | 3,834 | 323 | US$0.110 |
| Fixture | `graph` | 7,537 | 332 | US$0.207 |
| MarkovJunior | `source` | 8,662 | 381 | US$0.348 |
| MarkovJunior | `graph` | 13,562 | 550 | US$0.577 |

Claude input tokens include Claude Code's fixed per-call overhead, so they are larger than the context sent. Equivalent cost is Claude Code's list-price estimate; nothing was billed, because the runs used a subscription.

Usage records were matched to answers by position in the run's `execution_order`, and the question text was checked. The adapter's own `mode` field was not used. It infers the mode from the presence of graph paths, so it labelled one graph answer as source: in `fixture-rc-run-declarations`, the graph context contained no graph paths.

## Findings

1. **The graph's benefit on MarkovJunior is coverage.** In all four questions that graph mode won, source mode abstained. Graph mode answered from extracted edges whose source lines were not among the retrieved excerpts: `markov-static-path` (`Interpreter.Load → Node.Factory → Node.Load`), `markov-rc-wfc-factory`, `markov-rc-output` and `markov-rc-rulenode-loads`. When both modes answered, they agreed.
2. **Both modes abstained rather than guess.** No claim was graded incorrect or unsupported, and every abstention on an unanswerable question was correct. The database question has a lexical distractor (a `database` variable in `Search.cs`), and both modes correctly abstained on it. With this model, the risk is missing answers, not wrong ones.
3. **Retrieval misses cause most of the lost coverage.** In `markov-rc-main-grid-path`, `markov-rc-run-go-path` and `markov-rc-branch-self`, both modes abstained because the lines with the answer (for example `Program.cs:40` and `Node.cs:53`) were never retrieved, and the graph context did not supply those edges either. In `markov-rc-output`, source mode retrieved only `Program.cs:1-15`, while the answer is in lines 67–73. Retrieval works on 40-line chunks and lexically matching files, such as `GUI.cs`, often take the top slots.
4. **Graph context can distract on cycle questions.** In `markov-cycle`, the graph context offered many unrelated edges (`Node → MapNode`, `Node → OverlapNode`, …). The answer recovered only the inheritance step, and it said that it could not see an `Interpreter → Branch` edge, although the index has one (`Interpreter.root`/`current` are `Branch` fields). Source mode recovered two of the three facts.
5. **Graph evidence follows outgoing relationships only.** `archie/graph_evidence.py` (`nearby_paths`) expands seeds with `query_neighborhood` in the outgoing direction only. Reverse-dependency questions therefore get no incoming edges, as in `fixture-reverse`, where the `Controller → IService` edges were missing. Those questions were still answered from source excerpts. Depth-3 paths (`markov-rc-overlap-path`) were also incomplete. Including incoming neighbourhoods and reviewing the depth limit are the two most direct ways to improve graph mode.
6. **Graph mode sometimes adds nothing.** In `fixture-rc-run-declarations`, the graph context had no paths and was the same size as the source context.
7. **The cost is roughly double the context for this coverage gain.** On MarkovJunior, graph mode sent 1.96× the context and cost 1.66× as much, and pipeline latency rose by 3 s per answer.

## Qualitative comparison with the earlier Qwen3-4B runs

Victor's earlier Qwen3-4B runs answered Victor's 8 development questions on each benchmark: `run:c0fe32b074bb44e991378e86aab4452d` (fixture) and `run:3c829674c0f34f948e5acee6170f1259` (MarkovJunior). Rosa reviewed those runs qualitatively on 11 November 2026, in the walkthrough files `WALKTHROUGH-fixture.md` and `WALKTHROUGH-markovjr.md`, which are not in this repository. Those grades say whether an answer is correct, partial or incorrect, and whether its citations support it. They are not atomic-fact F1. **This section is a qualitative comparison only; the Qwen and Claude numbers are not pooled.**

- **Both models received the same evidence.** The context-token counts per answer match the Claude runs exactly, for example 2,023 / 3,876 tokens for `markov-loop` and 469 / 905 for `fixture-interface` (source / graph). Retrieval and graph selection are deterministic for a given index and question, so differences between the runs come from the answering model.
- **The source-mode retrieval miss is model-independent.** In `markov-static-path`, both Qwen and Claude abstained in source mode and answered correctly in graph mode. The evidence, not the model, decides this case.
- **Qwen invented an answer where Claude abstained.** In graph mode on `fixture-insufficient`, Qwen made a claim about the "database schema" and cited `Controller.cs`. Rosa graded this as a failed abstention with an unsupported claim. Claude abstained correctly in both modes on all five unanswerable questions.
- **Qwen gave more partial and incorrect answers on the fixture.** It answered `fixture-base-path` incorrectly in source mode (through `IService` injection instead of `Service → BaseService`). It was partial on `fixture-reverse` in both modes, where it missed that `Service` implements `IService`. Claude recovered every fact on these questions.
- **Both models are distracted on the cycle question.** On `markov-cycle`, Qwen's graph answer cited `MarkovNode` constructor-use edges instead of the `Node → Interpreter → Branch → Node` cycle. Claude's graph answer was also pulled towards unrelated edges (Finding 4). In both runs this question was partial in both modes.
- **Qwen's citations were weaker.** Several of its answers were correct but cited the wrong region or an unreadable graph path. No Claude claim was graded unsupported.

The 100% precision in this report is therefore partly a property of Claude. A 4B model given the same evidence makes unsupported claims, so the protocol's separate counting of incorrect and unsupported claims matters for the formal Qwen runs.

## Review observations

- `question:fixture-insufficient` asks about a "database schema", but its review note still says "PostgreSQL". It should say "a database".
- **MarkovJunior provenance can probably be verified now.** `MARKOVJUNIOR.md` and the benchmark say the snapshot has no verified upstream revision. A checkout of `https://github.com/mxgmn/MarkovJunior` reproduces the benchmark's source content hash (`sha256:b2534eee…`) for every commit from `f9716e3` to `42aaf24bcf54ae164fba49c0a59348297904a676` (19 March 2026). The hash was computed by applying the indexer's rule to the `.cs` files and the project file. The team could record `42aaf24` as the revision.
- Extraction status is `partial` on MarkovJunior. The only diagnostics are NuGet vulnerability warnings for `SixLabors.ImageSharp` 3.1.12, which do not affect static extraction.
- On the approved upstream commit, one test still expected draft benchmarks. It was updated in this branch.

## Limitations

- **Small and exposed sample.** There are 16 answerable MarkovJunior questions, and only 6 of them are multi-hop. Victor's questions were used during development, and none of these questions is held out. The frozen held-out questions in `benchmarks/HELDOUT.md` were deliberately not run. No uncertainty interval is reported, because the sample is too small for one to mean much, and the protocol's clustering plan is not settled yet. These results support no research claim.
- **One reviewer.** The consistency check that followed was not blind to mode. A second independent grader is needed before formal runs.
- **Claude, not Qwen.** The Claude revision cannot be pinned through the CLI. Claude abstained readily, while a 4B model may guess instead, so precision results may not carry over.
- **Precision unit.** Precision is per claim as written, not per atomic proposition, as protocol step 3 asks.
- **One run per mode.** The two modes saw different retrieval budgets (top-k 5 on the fixture, 8 on MarkovJunior), which is the same in both modes within each benchmark. Run-to-run variance was not measured.
- **Max output tokens.** `--max-new-tokens` is recorded but not enforced by the CLI adapter.

## Recommendations

1. Add incoming neighbourhoods for seeds in `graph_evidence.py`, and review the depth limit for depth-3 paths.
2. Investigate retrieval misses on files such as `Program.cs` and `Node.cs`, for example with symbol-aware seeding from the question.
3. Expand the held-out set before any formal run. A first set of four questions (three multi-hop) is frozen in `benchmarks/HELDOUT.md` and has never been run; it needs a second reviewer and more questions. The gap between development and new questions shows why it matters.
4. Score claims as atomic propositions and add a second blind grader.
5. Repeat the runs with Qwen3-4B on a GPU machine, using the same benchmarks and `archie analyze`, for the comparison the project is designed for.

## Reproducing the analysis

```bash
archie analyze benchmarks/results/markovjunior-claude-sonnet \
  --review benchmarks/results/markovjunior-claude-sonnet/review.json \
  --benchmark benchmarks/markovjunior-v1.json \
  --output benchmarks/results/markovjunior-claude-sonnet/analysis.json \
  --subset 'Victor questions=^question:(?!.*-rc-)' --subset 'second-reviewer questions=-rc-'
```

The same command works for `fixture-full-claude-sonnet` with `benchmarks/fixture-v1.json`. `archie analyze` reads the run, review and benchmark and never writes to them. It refuses an incomplete review, a review for another run, or an output path that would overwrite an input, and it records the SHA-256 of each input in `analysis.json`.

## Files

Each of `fixture-full-claude-sonnet/` and `markovjunior-claude-sonnet/` contains:

| File | Content |
| --- | --- |
| `experiment.json` | Frozen configuration, execution order and raw answer records (unchanged copy of the run) |
| `summary.json` | Runner summary: status counts, structural citation checks, mean tokens and latency |
| `review.json` | Blind human grading (claim labels, fact matches, abstentions, notes) |
| `analysis.json` | Output of `archie analyze`: per-answer scores, mode summaries, paired comparisons and subsets |
| `claude-usage.jsonl` | Claude Code usage per call (tokens, latency, model served, equivalent cost) |
