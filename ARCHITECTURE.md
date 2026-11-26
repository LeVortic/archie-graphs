# ArchiE Graphs Software Architecture

Status: V1 implementation and proposed interfaces

## Purpose

ArchiE Graphs V1 indexes a local C# solution, preserves source-backed dependencies, retrieves evidence, and compares source-only answers with graph-augmented answers from a local language model.

The architecture separates deterministic analysis from probabilistic retrieval and generation. Only deterministic components may create graph relationships or source citations.

## System context

```mermaid
flowchart LR
    User[Developer or researcher] --> CLI[archie CLI]
    CLI --> Index[Index workflow]
    CLI --> Ask[Ask workflow]
    CLI --> Inspect[Inspect workflow]
    CLI --> Evaluate[Evaluate workflow]
    CLI --> Retrieve[Retrieve workflow]
    CLI --> Review[Review markdown workflow]
    CLI --> Analyze[Analyze workflow]
    Index --> Repo[(Local C# repository)]
    Index --> Published[(Published index)]
    Published --> Ask & Inspect & Retrieve & Evaluate & Review
    Results --> Review & Analyze
    Human[Human reviewer] --> Analyze
    Analyze --> Scores[(Factual analysis)]
    Ask --> LocalModels[(Local embedding and LLM runtimes)]
    Index & Retrieve & Evaluate --> LocalModels
    Evaluate --> Benchmark[(Versioned benchmark)]
    Evaluate --> Results[(Experiment results)]
```

## Runtime components

```mermaid
flowchart TB
    subgraph Python[Python CLI process]
        CLI[CLI and composition root]
        Index[Index orchestration]
        Ask[Shared ask orchestration in CLI]
        Evaluate[Paired evaluation]
        Inspect[NetworkX graph queries]
        Retrieval[Source retrieval]
        Answer[Prompt and citation validation]
        Validation[Contract validation]
    end
    Roslyn[Roslyn subprocess]
    Repository[(C# solution or project)]
    Files[(Published index)]
    Embeddings[Local embedding runtime]
    LLM[Local generation subprocess]
    Runs[(Experiment and review records)]

    CLI --> Index & Ask & Inspect & Evaluate & Retrieval
    Index --> Roslyn --> Repository
    Roslyn -->|Versioned JSON| Index
    Index --> Validation --> Files
    Index -->|Optional embeddings| Embeddings
    Files --> Inspect & Retrieval
    Evaluate -->|Shared ask callback| Ask
    Evaluate --> Runs
    Ask --> Retrieval & Answer
    Ask -->|Graph mode| Inspect
    Retrieval --> Embeddings
    Answer --> LLM
```

## Index data flow

```mermaid
sequenceDiagram
    participant C as CLI
    participant I as Index orchestration
    participant X as Roslyn subprocess
    participant V as Contract validation
    participant A as Index staging directory

    C->>I: index(solution or project)
    I->>A: Create staging and building manifest
    I->>V: Validate extractor request
    I->>X: Send request on stdin
    X-->>I: Return versioned result on stdout
    I->>A: Save raw extractor JSON
    I->>V: Validate result and capture source snapshots
    alt Publishable extraction
        I->>A: Write graph export, snapshots, chunks and diagnostics
        opt Embedding requested
            I->>A: Write validated embeddings
        end
        I->>V: Validate complete manifest
        I->>A: Write manifest and atomically rename directory
        I-->>C: Published index path
    else Extraction, validation or publication fails
        I->>A: Preserve staging with failed manifest and error
        I-->>C: Failure with staging path
    end
```

## Ask and experiment flow

```mermaid
flowchart LR
    Ask[Standalone ask] --> SR[Source retrieval]
    Benchmark[Versioned benchmark] --> Gate[Check extraction coverage]
    Gate -->|Partial without override| Reject[Warn and reject]
    Gate -->|Complete extraction| Schedule[Paired schedule]
    Gate -->|Warn and allow partial override| Schedule
    Schedule --> SR
    SR --> Mode{Mode}
    SR -->|Source chunks in both modes| Context[Bounded evidence context]
    Mode -->|graph| GQ[Bounded graph query seeded from retrieved spans]
    GQ --> Context
    Context --> Prompt[Prompt builder]
    Prompt --> LLM[Local language model]
    LLM --> Validate[Answer and citation validation]
    Validate -->|ask| Output[Text or JSON answer]
    Validate -->|evaluate| Record[Checkpoint attempt]
    Record --> Summary[Operational and citation summary]
    Record --> Review[Human factual review]
    Review --> Analysis[Analyze factual scores]
```

## Module responsibilities

The table describes target responsibilities. Graph and storage ports and extractor probe and cancel remain proposed. The runtime diagram shows current wiring.

| Module | Owns | Must not own |
| --- | --- | --- |
| `cli` | Parsing commands, formatting output, exit codes | Graph logic, model calls |
| `application` | Use-case orchestration and policies | Extractor, Roslyn, or NetworkX details |
| `contracts` | Versioned input/output models and validation | I/O, retrieval, prompting |
| `extractor` | Extractor interface and source-backed relationship contract | Python graph construction |
| `graph` | NetworkX construction and bounded queries | Source parsing, LLM decisions |
| `source` | Chunking, line metadata, citation lookup | Dependency inference |
| `retrieval` | Embedding and vector-search ports/adapters | Answer wording |
| `answering` | Evidence selection, prompt creation, answer validation | Creating unsupported evidence |
| `evaluation` | Benchmark execution, result records, metrics | Production query policy |
| `storage` | Atomic artifact reads/writes and manifests | Business decisions |

## Proposed dependency direction

```mermaid
flowchart BT
    Contracts[Contracts and domain models]
    Ports[Ports and policies]
    Application[Application services]
    Adapters[Adapters: Roslyn or other extractor, NetworkX, vector index, model runtime, filesystem]
    CLI[CLI]
    Tests[Tests]

    Ports --> Contracts
    Application --> Ports
    Adapters --> Ports & Contracts
    CLI --> Application
    CLI -->|Composition root| Adapters
    Tests --> Contracts & Ports & Application & Adapters
```

Rules:

1. Dependencies point inward toward contracts and policies.
2. Application services depend on interfaces, not any extractor implementation, Roslyn, NetworkX, a vector library, or a model runtime.
3. Adapters translate external data into domain contracts.
4. Each extractor remains behind the shared interface and emits the same versioned file or standard-output contract.
5. CLI handlers stay thin and call one application service per use case.

## SOLID application

### Single Responsibility

- `IndexService` coordinates indexing only.
- `GraphQueryService` answers graph queries only.
- `CitationValidator` validates citations only.
- `ExperimentRunner` runs benchmark cases only.
- File, model, embedding, and graph adapters each wrap one external concern.

### Open/Closed

- Add a model runtime by implementing `LanguageModel`.
- Add an embedding backend by implementing `EmbeddingIndex`.
- Add a graph query by extending the graph query policy and result contract.
- Do not change application services for adapter replacement.

### Liskov Substitution

- Every adapter must honor timeout, error, ordering, and metadata guarantees in its port.
- A fake adapter used in tests must return the same contract shape and failure semantics.

### Interface Segregation

Keep ports narrow:

```text
Extractor.extract(input) -> ExtractedIndex
GraphQuery.direct(node, limit) -> GraphResult
GraphQuery.paths(source, target, limits) -> GraphResult
SourceIndex.search(query, limit) -> EvidenceChunk[]
EmbeddingIndex.upsert(chunks) / search(vector, limit)
LanguageModel.complete(prompt, settings) -> ModelResponse
ArtifactStore.read/write(manifest, artifact)
```

### Dependency Inversion

- Use cases depend on ports.
- Composition root selects concrete adapters.
- Domain contracts never import infrastructure libraries.
- Tests inject fakes without starting an extractor, Roslyn, NetworkX, or a model runtime.

## Evidence and trust boundaries

1. Treat repository files and extractor output as untrusted input. Validate paths, schemas, sizes, and versions.
2. Only resolved extractor relationships become `EXTRACTED` graph edges.
3. Unresolved symbols become diagnostics or explicitly marked `UNRESOLVED` records.
4. `INFERRED` relationships, if added later, cannot be presented as source fact.
5. Every answer citation must resolve to an indexed file and valid line range.
6. Run commands with networking disabled after provisioning dependencies and model caches. Model adapters use local files only.
7. Warn on partial extraction during inspection, answering, and evaluation. Evaluation requires an explicit development override and records extraction status.
8. Write artifacts atomically and keep failed experiment records.

## Contract schemas

The interchange boundary is JSON Schema Draft 2020-12. Schemas live in `schemas/`.

- `archie.extractor-request.v1` and `archie.extractor-result.v1` define the adapter boundary.
- `index-manifest.v1` defines artifact identity and publication state.
- `evidence-ref.v1` links claims to source spans, graph edges, or graph paths.
- `answer-record.v1`, `benchmark-question.v1`, and `experiment-record.v1` define evaluation data.
- `common.schema.json` defines IDs, source spans, diagnostics, nodes, edges, and claims.

Persisted objects reject unknown fields. Top-level contracts use `schema_version: archie.<contract>.v1` for major compatibility and optional `schema_revision` for additive revisions. A changed meaning or removed field requires a new major `vN` schema identifier.

### Canonical identity

- IDs use a namespace prefix, such as `project:App` or `type:App.CheckoutController`.
- Project identity is part of every symbol identity.
- Artifact paths are repository-relative, use `/`, and cannot contain `..`.
- Lines and columns are one-based and inclusive.
- Content hashes use lowercase `sha256:<64 hex digits>`.
- Producers sort persisted arrays deterministically.

### Proposed extractor port

```text
probe(input) -> capabilities and diagnostics
extract(request) -> ExtractorResult
cancel(operation_id) -> acknowledgement
```

Adapters advertise capabilities. The Python pipeline consumes only the shared result contract and must not import Roslyn types or assume unsupported node kinds.

### Diagnostics and failure states

Every diagnostic has `code`, `severity`, `message`, `component`, and `recoverable`; optional path and source span identify the cause. Extractors return `succeeded`, `partial`, or `failed`. Indexes use `building`, `complete`, or `failed`.

### Artifact publication

1. Write to a temporary index directory.
2. Write a `building` manifest.
3. Validate artifacts and cross-references.
4. Set manifest to `complete` only after validation.
5. Rename the completed directory atomically.
6. Preserve `failed` manifests and diagnostics.

## Artifact layout

```text
artifacts/
  index/<index-id>/
    manifest.json
    extractor.json
    graph.json              # export
    source-snapshots.json   # referenced source files for span validation
    source-chunks.jsonl
    embeddings.json        # optional
    diagnostics.json
  evaluations/<run-directory>/
    experiment.json
    summary.json
    review-template.json
    review.MD
```

The index manifest records source content hash, extractor identity and interface version, artifact paths, and creation time. Embedding identity is stored in `embeddings.json`. NetworkX rebuilds from `extractor.json` and validates spans using the published snapshots. Earlier indexes require their original checkout for graph operations. Experiment records capture model and runtime identities, configuration, and extraction status.

## Testing strategy

- Unit tests: contracts, validators, graph algorithms, chunking, citation rules, prompt construction, and metrics.
- Contract tests: every adapter satisfies timeout, ordering, metadata, and error guarantees.
- Integration tests: fixture solution through extractor, index, graph query, retrieval, and answer validation.
- Golden tests: stable extractor JSON, graph query JSON, and CLI output.
- Evaluation tests: metric calculations on hand-built answers, including unsupported claims and missing citations.
- Reproducibility test: clean checkout runs the fixture workflow with fixed seed and produces valid manifests.
- Schema contract tests: valid fixtures pass; missing fields, unknown fields, invalid enums, bad paths, and incompatible versions fail.

## Non-functional rules

- Deterministic ordering for all persisted collections.
- Bounded graph traversal and bounded prompt context.
- Structured errors with actionable diagnostics.
- No global mutable state in application services.
- Explicit timeouts around external processes and model calls.
- Logs never include secrets or full source content by default.
