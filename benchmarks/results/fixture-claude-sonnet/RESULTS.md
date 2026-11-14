# Fixture benchmark: Claude Sonnet 5.5 run on the approved benchmark

Reviewer: Rosa Cortes · Run: `run:7cb1434e40c142ff92fad9e1551a3bf1` · Date: 14 November 2026

## Purpose

This run checks the full evaluation workflow end to end on the controlled fixture, using the **approved** `fixture-v1.json` (206f926), before moving on to MarkovJunior. It is also the independent second review the protocol asks for: Victor approved the questions, and this run grades the model's answers to them blind.

The fixture questions are calibration material, not held-out evidence, so these results support no research claim about the graph benefit.

## Setup

| Item | Value |
| --- | --- |
| Benchmark | `benchmarks/fixture-v1.json` (`fixture-development-v1`, review status `approved`), benchmark hash `sha256:51eca4d6…` |
| Source snapshot | `sha256:450aba2d1f8f30230a7cda5eda6481632adabd6b9ca0515db80eadaccd4a1f7d` (matches the benchmark) |
| Answering model | **Claude Sonnet 5.5 (`claude-sonnet-5-5`) through the Claude Code CLI, not Qwen3-4B** |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` @ `1110a243`, CPU |
| Settings | seed 42, top-k 5, context budget 4,096 tokens, both modes (`source`, `graph`); no `--allow-draft` |
| Machine | macOS, Intel x86_64, no GPU; Python 3.12.10; torch 2.2.2, transformers 4.57.6, sentence-transformers 5.7.0 |

**Why Claude instead of Qwen.** Qwen3-4B is not practical on an Intel Mac without a GPU. As agreed with the team, a local adapter replaced Qwen with Claude through the Claude Code CLI. The adapter is kept outside the repository. It reuses the project's prompt, evidence selection, citation checks and answer validation unchanged. Claude ran with no tools, no session persistence and an empty working directory, so it saw only the supplied excerpts. Context was still counted with the pinned Qwen3 tokenizer, so evidence selection under the 4,096-token budget is the same as in Qwen mode.

**These results are not comparable with Qwen results and must not be pooled with them.**

## Grading method

Grading followed `benchmarks/PROTOCOL.md`: a human reviewer did it blind, with each answer shown as "A" or "B" in an order shuffled per question and per run, and its mode hidden until grading finished. For each answer:

- each claim was labelled `ok` (correct and asked), `extra` (correct but not asked), `incorrect`, or `unsupported` (the cited evidence does not support it);
- each expected fact was marked as recovered or not, by meaning rather than wording;
- abstention questions were marked as correct or incorrect abstention.

Precision is the number of correct claims (`ok` + `extra`) divided by all claims. Recall is the number of recovered facts divided by the expected facts. F1 is the macro average per question over the six answerable questions. The two abstention questions are reported separately. The full grading is in `review.json`.

## Results

| Mode | Answers without errors | Precision | Recall | F1 | Correct abstentions | Incorrect / unsupported claims |
| --- | --- | ---: | ---: | ---: | --- | --- |
| `source` | 8/8 | 1.00 | 1.00 | **1.00** | 2/2 | 0 / 0 |
| `graph` | 8/8 | 1.00 | 1.00 | **1.00** | 2/2 | 0 / 0 |

Correct but not-asked (`extra`) claims: 3 in `source` mode and 4 in `graph` mode. The automated structural check found every citation valid: 9/9 in `source` mode and 21/21 in `graph` mode. Neither mode invented an answer for the two insufficient-evidence questions.

### Usage per answer (mean)

| Mode | Context sent (Qwen tokens) | Claude input tokens | Claude output tokens | Generation latency | Pipeline latency | Equivalent API cost (8 answers) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `source` | 473 | 4,676 | 273 | 10.6 s | 11.0 s | US$0.095 |
| `graph` | 1,679 | 7,208 | 335 | 10.9 s | 12.3 s | US$0.145 |

Claude input tokens include Claude Code's own per-call overhead in addition to the evidence. Equivalent cost is the list-price estimate reported by Claude Code; nothing was billed because the run used a Claude subscription. Per-call records are in `claude-usage.jsonl`.

## Findings

1. **The workflow works end to end on a clean second machine.** Installation, extraction, indexing, embeddings, retrieval, both answering modes, paired evaluation on the approved benchmark and blind grading all completed. The test suite gave 155 passed and 1 skipped (Qwen decoding library not installed).
2. **The fixture cannot separate the two modes.** Both reach F1 = 1.00, which is expected for a five-type fixture. Mode comparison needs MarkovJunior and more multi-hop questions.
3. **Graph mode delivered about 3.5× more context with no accuracy gain on this fixture.** Latency was similar.
4. **Graph evidence only follows outgoing relationships.** In `question:fixture-reverse` ("which types depend on IService"), the graph context contained only `Service → IService` and `Service → BaseService`. The incoming `Controller → IService` field-use and constructor-use edges exist in the index but were not supplied. The answer was still correct because the source excerpt showed them. This happened on both the draft and the approved runs. The cause is that `archie/graph_evidence.py` (`nearby_paths`) expands seeds with `query_neighborhood` in the outgoing direction only, so the graph mode cannot supply evidence for reverse-dependency questions. This deserves a decision before the formal runs: either include incoming neighbourhoods for seeds, or report it as a known limitation for the `reverse_dependency` category.
5. **The answers tended to add correct but unasked detail**, such as runtime caveats, overrides and line numbers. In `fixture-reverse`, both modes added that Controller calls `service.Run()`, while the review note limits that question to type-to-type relationships. Both of those claims were graded `ok` overall because their main content answers the question.

## Review observations on the approved benchmark

- `question:fixture-insufficient` now asks about a "database schema", but its review note still says "do not require a claim that PostgreSQL is absent everywhere". The note should say "a database" to match the question.
- `REVIEW.md` was reconciled with the approved JSON in this branch (f8fef82).

## Limitations

- The Claude model version cannot be pinned through the CLI; it is recorded as `unpinned`.
- `--max-new-tokens` is recorded but not enforced by the CLI adapter.
- Token counts differ between Claude and Qwen: the context budget uses the Qwen tokenizer, while usage is Claude's own count.
- There was one reviewer for this grading.
- Installing on Intel macOS needed `torch==2.2.2` and `transformers<5`; current PyTorch has no Intel macOS wheels, and transformers 5 requires PyTorch 2.6 or later. macOS can also mark the editable-install `.pth` file as hidden, which Python 3.12 then skips; `chflags nohidden` on that file fixes it.

## Files

| File | Content |
| --- | --- |
| `experiment.json` | Frozen configuration, execution order and raw answer records |
| `summary.json` | Status counts, structural citation checks, mean tokens and latency |
| `review.json` | Blind human grading (claim labels, fact matches, abstention, notes) |
| `claude-usage.jsonl` | Claude Code usage per call (tokens, latency, model served, equivalent cost) |
