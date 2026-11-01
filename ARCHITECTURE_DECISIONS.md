# Architecture Decision Records

## ADR-001: Split extraction and orchestration behind an extractor interface

Status: Accepted

### Context

Roslyn Workspaces provide the first required C# semantic analysis. Future repositories may need different extractors or languages. NetworkX, retrieval, experiment execution, and local-model integration fit the Python ecosystem. One process would couple unrelated runtimes and make failures harder to isolate.

### Decision

Define a language-neutral extractor interface and versioned output contract. Use a small .NET Roslyn adapter first. Each future extractor adapter emits the same contract through a file or standard output. A Python CLI validates that contract and owns graph construction, retrieval, answering, and evaluation.

### Consequences

- Clear ownership and independent tests.
- Future extractors can connect without changing the Python application layer.
- Reproducible extractor artifacts can be inspected without running the model stack.
- JSON schema versioning becomes mandatory.
- Cross-process diagnostics and cancellation need explicit handling.

## ADR-005: Use versioned JSON Schema contracts for interchange

Status: Accepted

### Context

Different extractor adapters must connect without importing each other’s types. The graph, retrieval, and evaluation layers also need stable persisted records.

### Decision

Use JSON Schema Draft 2020-12. Keep shared types in `schemas/common.schema.json`. Reject unknown fields in persisted objects. Additive changes use a minor release; incompatible changes create a new major `vN` schema identifier.

### Consequences

- Adapters can be tested independently and replaced.
- Schema fixtures become part of the compatibility contract.
- Cross-record checks, such as edge endpoints and evidence IDs, still require application-level validation.

## ADR-002: Keep evidence attached to relationships

Status: Accepted

### Context

Architecture answers are only useful when claims can be checked against source. A graph edge without a file and line range can mislead the model and the evaluator.

### Decision

Every extracted relationship stores source path, line range, edge type, project identity, and extraction status. Query results preserve this metadata.

### Consequences

- Storage is larger.
- Citation validation is straightforward.
- Relationships without source evidence remain diagnostics or explicitly non-extracted records.

## ADR-003: Use ports for model, embedding, storage, and graph adapters

Status: Accepted

### Context

The study needs one local model now, but tests must not require model hardware. Future adapters must not change application logic.

### Decision

Application services depend on narrow interfaces. Concrete local runtimes are selected only in the composition root. Tests inject deterministic fakes.

### Consequences

- Slightly more wiring.
- Fast unit tests and replaceable infrastructure.
- Ports must define error, timeout, ordering, and metadata behavior precisely.

## ADR-004: Equalize source and graph context budgets

Status: Accepted

### Context

A graph mode with more context can appear better because it receives more tokens, not because graph evidence helps.

### Decision

The experiment runner uses the same model, generation settings, question set, and context budget for both modes. It records actual context size and truncation.

### Consequences

- Some graph paths may be truncated.
- Results are more defensible.
- Context assembly needs deterministic prioritization.


## ADR-006: Portable local source embeddings with optional CUDA

Status: Accepted

### Context

The development machine has an RTX 5080 Laptop GPU, while other study machines may have only a CPU. Embedding generation should use available hardware without tying published indexes to CUDA or a hosted service.

### Decision

Use Sentence Transformers with `sentence-transformers/all-MiniLM-L6-v2`, selecting CUDA automatically when available and allowing explicit CPU/CUDA selection. Record the resolved model commit, runtime versions, dimensions, normalization, and token budget. The device is run metadata rather than embedding identity. Token-aware source chunks retain deterministic content IDs and exact source spans. Cache vectors in SQLite by model identity and chunk content; publish validated JSON vectors atomically with the index. Use exact local cosine search for the current study size.

### Consequences

- GPU generation and CPU querying use the same artifact format and model identity.
- First use downloads weights and optional dependencies; inference never sends repository text remotely.
- Runtime/model changes invalidate the cache; device-only changes retain reuse with minor numerical differences possible.
- Source snapshots allow retrieval without the original checkout.
- Linear in-memory search is intentionally limited to local study indexes; a larger corpus may need a dedicated vector index.
- This general-purpose model is an initial retrieval baseline; benchmark quality still needs evaluation before research claims.
