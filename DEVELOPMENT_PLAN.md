# ArchiE Graphs Development Plan

## 0. Define the baseline

1. Freeze the research question, hypotheses, supported C# constructs, answer format, and benchmark metrics.
2. Record tool versions, local model runtime, hardware, operating system, and reproducibility commands.
3. Choose one local embedding model, one local language model, and one vector-index implementation.
4. Define JSON Schema Draft 2020-12 contracts under `schemas/` for extractor requests/results, manifests, evidence, answers, benchmarks, experiments, and shared types.
5. Define canonical ID, path, source-span, hash, ordering, enum, major `schema_version`, additive `schema_revision`, compatibility, and failure-state rules.

**Gate:** A fresh checkout can install dependencies and pass valid/invalid schema contract tests.

## 1. Create the repository skeleton

1. Add an extractor contract and a .NET Roslyn adapter as the first implementation.
2. Add a Python CLI package for validation, graph construction, retrieval, asking, inspection, and evaluation.
3. Add shared sample fixtures: a small buildable `.sln`, projects, inheritance, interface implementation, field and constructor use, method calls, cycles, and an unresolved reference.
4. Add unit-test, integration-test, lint, format, and schema-validation commands.
5. Add setup and usage documentation with the exact local-model prerequisites.
6. Add schema fixtures and contract tests for a Roslyn-shaped result, a fake extractor, malformed output, missing fields, unknown fields, invalid enums, bad paths, incompatible major versions, and newer minor revisions.

**Gate:** Fixture solution indexes through the CLI and produces validated versioned JSON.

## 2. Build the C# extractor

1. Define the extractor interface for solution loading, symbol extraction, relationship extraction, diagnostics, and source locations.
2. Define `probe`, `extract`, and `cancel` behavior, capability negotiation, timeout rules, and partial-failure semantics.
3. Implement the first adapter with Roslyn Workspaces for `.sln` and `.csproj` inputs.
4. Extract projects, namespaces, types, and methods with canonical IDs and project identity.
5. Extract inheritance, interface implementation, field type use, constructor type use, and resolved method-call relationships.
6. Attach repository-relative file paths and one-based inclusive source spans to every resolved relationship.
7. Emit typed edges, source-backed nodes, unresolved references, structured diagnostics, extractor identity, and input metadata.
8. Keep unresolved symbols visible as diagnostics; never invent source evidence.
9. Add deterministic ordering so repeated runs produce stable JSON.

**Gate:** Fixture tests verify symbols, edge types, line ranges, unresolved references, and stable output.

## 3. Build the NetworkX graph layer

1. Validate extractor JSON before graph construction.
2. Build a `MultiDiGraph` keyed by qualified symbol identifier plus project identity.
3. Preserve edge type, source span, confidence/status, and extractor provenance as edge attributes.
4. Implement direct dependencies, reverse dependencies, bounded neighborhoods, dependency paths, and cycle detection.
5. Define limits for traversal depth, node count, and returned paths.
6. Return structured query results that retain source evidence.
7. Validate node/edge cross-references before publishing the graph artifact.

**Gate:** Graph tests cover direct and reverse queries, multiple edge types, path bounds, cycles, missing nodes, and cross-project identity.

## 4. Add source retrieval

1. Split source into deterministic chunks with file and line metadata.
2. Generate local embeddings and store the vector index beside the versioned index artifact.
3. Implement top-k source retrieval with stable scoring and citation metadata.
4. Add cache invalidation based on source content and embedding-model identity.
5. Expose retrieval diagnostics: selected chunks, scores, token estimates, and skipped inputs.

**Gate:** Re-indexing unchanged input reuses cached embeddings; changed source invalidates only affected chunks.

## 5. Add local-model answering

1. Add one adapter for the selected local language-model runtime.
2. Define a prompt that requires answers to cite only supplied evidence.
3. Implement `source` mode using retrieved source chunks.
4. Implement `graph` mode using source chunks plus bounded graph paths and graph evidence.
5. Return plain-text answers and JSON records containing question, mode, answer, citations, evidence, timing, context size, model versions, and errors.
6. Represent answer claims with support status and stable evidence IDs; reject or label unsupported claims when evidence is absent.

**Gate:** CLI answers work in both modes and every citation maps to an existing file and line range.

## 6. Finish the CLI

1. Implement `archie index path/to/App.sln`.
2. Implement `archie ask "..." --mode source|graph`.
3. Implement `archie inspect cycles` and the other graph query operations needed by the study.
4. Implement `archie evaluate benchmark.json`.
5. Add clear failures for invalid paths, non-buildable solutions, malformed extractor output, unavailable model runtimes, and missing indexes.
6. Keep human output concise and provide machine-readable JSON for batch runs.
7. Publish an index only after manifest, artifact, and cross-reference validation; preserve failed manifests.

**Gate:** End-to-end smoke test passes from a clean checkout on the fixture solution.

## 7. Create and review the benchmark

1. Write architecture questions over the fixture and selected real repositories.
2. Label expected answer facts, required evidence, dependency depth, and acceptable citations.
3. Include questions requiring zero, one, and two-or-more dependency steps.
4. Include cycles, reverse dependencies, cross-project paths, unresolved references, and questions with insufficient evidence.
5. Have a reviewer check question wording, labels, and answer criteria.
6. Version the benchmark and record repository commit hashes used to build it.

**Gate:** Benchmark annotations are complete and independent review issues are resolved.

## 8. Build the experiment runner

1. Run identical questions through source and graph modes with the same model, context budget, and generation settings.
2. Randomize or counterbalance mode order to reduce order effects.
3. Record answers, citations, retrieved evidence, graph paths, latency, context size, failures, and run metadata.
4. Add retries only for infrastructure failures; preserve failed attempts in the raw results.
5. Make runs resumable and deterministic from a seed.
6. Validate result records before analysis.

**Gate:** A complete run can be reproduced from benchmark version, source commits, model versions, configuration, and seed.

## 9. Analyze results

1. Compute answer fact precision, recall, and F1 against reviewed annotations.
2. Measure unsupported architectural claims as a separate metric.
3. Break results down by dependency depth, question type, repository, and failure class.
4. Report latency, context size, retrieval failures, unresolved-reference impact, and cost-free local runtime constraints.
5. Use paired comparisons between modes and report uncertainty, sample sizes, and exclusions.
6. Preserve raw records and generate reproducible tables and figures from them.

**Gate:** Analysis reruns without manual edits and supports or rejects H1 and H2 with stated limitations.

## 10. Documentation and delivery

1. Document architecture, schemas, installation, local models, CLI commands, troubleshooting, and limitations.
2. Add a CLI demonstration using a small public or fixture repository.
3. Package source code, tests, benchmark annotations, raw results, analysis scripts, and thesis material.
4. Add a final reproducibility checklist and clean-checkout verification.
5. Tag the release with extractor, graph schema, benchmark, model, and experiment versions.

**Final acceptance:** Clean setup succeeds; indexing, graph queries, both answer modes, benchmark evaluation, and analysis all run with cited evidence and reproducible outputs.

## Main risks and controls

- Extractor implementations can differ in resolution quality: keep unresolved references explicit, report diagnostics, and record adapter identity.
- Graph edges can overstate architecture: require source spans and distinguish extracted, unresolved, and inferred data.
- Local model quality or hardware may limit throughput: freeze model settings and report latency and failures.
- Benchmark labels can bias results: review labels independently and publish annotation rules.
- Context growth can favor graph mode unfairly: enforce equal context budgets and report actual context size.

## Deliberately out of scope

No web-hosted model, additional extractor adapters, production daemon, automatic code changes, distributed indexing, or flexible plugin system until the core study works. Future extractors must implement the shared extractor contract; the Python pipeline must not depend directly on Roslyn.
