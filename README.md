# ArchiE Graphs

The first working milestone indexes a local C# solution into validated, source-backed JSON artifacts. Python orchestrates the workflow; a separate Roslyn process resolves C# symbols. No model runtime is needed yet.

## Setup

Requires Python 3.11+ and the .NET 10 SDK. Run from this directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e . -r requirements-dev.txt
dotnet build extractor/ArchiE.Extractor/ArchiE.Extractor.csproj
dotnet build fixtures/csharp/Fixture.sln
.venv/bin/python -m pytest -q
.venv/bin/archie index fixtures/csharp/Fixture.sln
```

Use an editable source install for this milestone: the CLI locates the built extractor beside the Python source. Standalone wheel deployment is not supported yet. Integration tests skip explicitly if the extractor has not been built.

The SDK installation used during development reports `NETSDK1226` and cannot resolve its distro-specific apphost. On that installation, both build commands need:

```sh
dotnet build extractor/ArchiE.Extractor/ArchiE.Extractor.csproj -p:AllowMissingPrunePackageData=true -p:UseAppHost=false
dotnet build fixtures/csharp/Fixture.sln -p:AllowMissingPrunePackageData=true -p:UseAppHost=false
```

These flags work around that local installation; a normal SDK should use the standard commands.

## Indexing, step by step

1. `archie index` checks the input and creates a staging directory with a `building` manifest.
2. Python sends a versioned request to the Roslyn process, enforcing a 120-second timeout.
3. Roslyn loads the solution and resolves types, methods, inheritance, interface implementation, method calls, field types, and constructor dependencies. IDs contain project paths and documentation symbol identities. Edges contain inclusive source spans. Unresolved calls and compiler errors become diagnostics.
4. Python validates JSON Schema, unique IDs, project membership, edge endpoints, source containment, and source ranges. Unsupported or unbacked edges cannot enter the index.
5. Python writes extractor output, graph records, source snapshots, and diagnostics. It validates the complete manifest and renames the staging directory atomically.
6. Errors preserve a failed manifest in the staging directory. CLI failures return exit code 1; successful output identifies the published directory.

```sh
.venv/bin/archie index fixtures/csharp/Fixture.sln --output artifacts/index
```

Published indexes contain `manifest.json`, `extractor.json`, `graph.json`, `source-chunks.jsonl`, and `diagnostics.json`. Repeated extraction preserves content hashes, IDs, arrays, and source spans; index IDs and creation timestamps intentionally differ.

## Current boundaries

- Build or restore target projects before indexing so Roslyn can resolve references.
- Source and referenced projects must be inside the directory containing the input solution or project. Prefer a solution at the repository root for sibling projects.
- Relationships to external framework symbols are omitted. Partial extraction retains diagnostics and can produce a complete index of the validated subset; inspect `extractor.json` status.
- Published graph records remain JSON. The query layer builds a NetworkX `MultiDiGraph` from the validated extractor artifact, preserving parallel relationships and source evidence.
- Source snapshots use one chunk per referenced source file. Embeddings, retrieval, and answering are future milestones.
- Dependency edges link the owning type to an indexed type: `field_use` covers declared field types; `constructor_use` covers constructor parameter types and explicit or target-typed object creation. Each edge cites the type syntax or creation expression. External types are omitted; unresolved types remain diagnostics.
- Dependency extraction currently covers directly indexed named types. Array elements, generic type arguments, primary-constructor parameters, and constructor initializers are not traversed.
- Namespaces, cycles fixture coverage, capability probing, explicit cancellation messages, and full extractor failure contracts remain unfinished.
- Source files should remain unchanged during indexing. SDK, project imports, and external dependency changes are not yet captured in the source content hash.

Next graph milestone: bounded neighborhoods, dependency paths, and cycle queries.

## Query direct dependencies

First index the fixture, then use the published directory printed by `archie index`:

```sh
.venv/bin/archie inspect dependencies artifacts/index/INDEX_DIRECTORY 'type:App%2FApp.csproj:T%3AFixture.App.Controller'
.venv/bin/archie inspect dependents artifacts/index/INDEX_DIRECTORY 'type:Core%2FCore.csproj:T%3AFixture.Core.IService' --limit 10
```

Replace `INDEX_DIRECTORY` with the actual directory name. Exact symbol IDs are available in that index's `extractor.json`; quoted IDs above apply to the supplied fixture.

`dependencies` returns outgoing relationships; `dependents` returns incoming relationships while preserving their original `from` and `to` endpoints. Both inspect one hop over all relationship kinds, without aggregating method calls into type-level dependencies. Results include nodes, original edges and citations, extractor identity, extraction status, diagnostics, and a `truncated` flag. The edge limit defaults to 100 and accepts 1–1000; at most limit + 1 nodes are returned. Results are deterministic for identical input regardless of artifact array ordering.

Queries accept only complete published manifests, validate the extractor contract and source evidence, and reject unknown symbol IDs. Partial extraction remains queryable and is labeled in results. Original source files must remain available and unchanged for evidence validation; queries do not rerun extraction or verify source content hashes against current disk contents. Loading and validating the index is not bounded by the query result limit. Queries do not modify published indexes.
