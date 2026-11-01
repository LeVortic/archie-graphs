# ArchiE Graphs

The first working milestone indexes a local C# solution into validated, source-backed JSON artifacts. Python orchestrates the workflow; a separate Roslyn process resolves C# symbols. Indexing and graph queries need no model runtime. Source retrieval optionally uses local Sentence Transformers embeddings.

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
- Source snapshots use deterministic chunks of up to 40 lines and 2,000 characters, with exact UTF-16 source spans. Embedding-enabled indexes also split to the model token budget. Answer generation remains a future milestone.
- Dependency edges link the owning type to an indexed type: `field_use` covers declared field types; `constructor_use` covers constructor parameter types and explicit or target-typed object creation. Each edge cites the type syntax or creation expression. External types are omitted; unresolved types remain diagnostics.
- Dependency extraction currently covers directly indexed named types. Array elements, generic type arguments, primary-constructor parameters, and constructor initializers are not traversed.
- Namespaces, capability probing, explicit cancellation messages, and full extractor failure contracts remain unfinished.
- Source files should remain unchanged during indexing. SDK, project imports, and external dependency changes are not yet captured in the source content hash.

Graph query milestone complete: direct/reverse dependencies, bounded neighborhoods, dependency paths, and cycle queries. Source retrieval is implemented; next development milestone: local-model answering.

## Query direct dependencies

First index the fixture, then use the published directory printed by `archie index`:

```sh
.venv/bin/archie inspect dependencies artifacts/index/INDEX_DIRECTORY 'type:App%2FApp.csproj:T%3AFixture.App.Controller'
.venv/bin/archie inspect dependents artifacts/index/INDEX_DIRECTORY 'type:Core%2FCore.csproj:T%3AFixture.Core.IService' --limit 10
```

Replace `INDEX_DIRECTORY` with the actual directory name. Exact symbol IDs are available in that index's `extractor.json`; quoted IDs above apply to the supplied fixture.

`dependencies` returns outgoing relationships; `dependents` returns incoming relationships while preserving their original `from` and `to` endpoints. Both inspect one hop over all relationship kinds, without aggregating method calls into type-level dependencies. Results include nodes, original edges and citations, extractor identity, extraction status, diagnostics, and a `truncated` flag. The edge limit defaults to 100 and accepts 1–1000; at most limit + 1 nodes are returned. Results are deterministic for identical input regardless of artifact array ordering.

Queries accept only complete published manifests, validate the extractor contract and source evidence, and reject unknown symbol IDs. Partial extraction remains queryable and is labeled in results. Original source files must remain available and unchanged for evidence validation; queries do not rerun extraction or verify source content hashes against current disk contents. Loading and validating the index is not bounded by the query result limit. Queries do not modify published indexes.

## Multi-hop graph queries

Use the same published index directory and exact symbol IDs:

```sh
.venv/bin/archie inspect neighborhood artifacts/index/INDEX_DIRECTORY 'type:App%2FApp.csproj:T%3AFixture.App.Controller' --max-depth 2
.venv/bin/archie inspect paths artifacts/index/INDEX_DIRECTORY 'type:App%2FApp.csproj:T%3AFixture.App.Controller' 'type:Core%2FCore.csproj:T%3AFixture.Core.BaseService' --max-depth 3 --max-paths 10
.venv/bin/archie inspect cycles artifacts/index/INDEX_DIRECTORY --max-depth 3 --max-paths 10
```

Re-index the fixture to include `Core/Cycles.cs`. It supplies a two-type field dependency cycle. No model runtime or new dependency is needed.

- `neighborhood` follows outgoing relationships breadth first; `--reverse` follows incoming relationships without reversing stored evidence. It returns edges expanded from nodes strictly inside the depth boundary, rather than every edge between returned nodes.
- `paths` returns directed simple paths between two symbols. Nodes cannot repeat within a path. Parallel relationships produce distinct edge paths. A query from a symbol to itself returns one empty path; use `cycles` for non-empty loops.
- `cycles` searches the whole index for directed simple cycles, including self-loops. Cycles begin at their smallest symbol ID, avoiding duplicate rotations. Parallel relationships produce distinct edge cycles. This is symbol-level evidence; method calls and type dependencies are not combined into inferred type-level paths.

New query limits:

| Option | Default | Allowed | Meaning |
| --- | --- | --- | --- |
| `--max-depth` | 2 for neighborhoods; 3 otherwise | 1–10 | Maximum edges per traversal path |
| `--max-nodes` | 100 | 1–1,000 | Maximum distinct nodes visited during search |
| `--max-edges` | 1,000 | 1–1,000 | Maximum neighborhood edges |
| `--max-paths` | 10 | 1–100 | Maximum returned paths or cycles |
| `--max-steps` | 10,000 | 1–100,000 | Maximum examined edges across path/cycle search, including dead ends |

Depth defines the requested search scope: longer paths are excluded and do not alone set `truncated`. Other exhausted limits produce `truncated: true` and `truncation_reasons`. Path/cycle result limits use one additional match to detect truncation; the node and step budgets still apply to that check. A truncated empty result does not prove no path or cycle exists. Traversal order is deterministic, but path results are not ranked by shortest length.

`paths` and `cycles` contain ordered lists of edge IDs. Their `edges` array holds each referenced edge once, with original source spans, kind, status, and confidence. `nodes` holds those endpoints (plus the source for a path query). All new results retain extractor provenance, extraction status, and diagnostics. At most 1,000 distinct edges can be returned by paths/cycles (100 paths × 10 edges). Limits apply after full index loading and validation; they do not cap input artifact size.

## Local source retrieval

Install the optional retrieval dependencies. GPU and CPU installations use the same model and portable JSON vector format. For the RTX 5080 tested on this machine:

```sh
.venv/bin/python -m pip install 'torch>=2.7,<3' --index-url https://download.pytorch.org/whl/cu128
.venv/bin/python -m pip install -e '.[retrieval]'
.venv/bin/archie index fixtures/csharp/Fixture.sln --output artifacts/index --embed --device auto
```

On a fresh CPU-only system, install PyTorch from its CPU wheel index first, then the retrieval extra:

```sh
.venv/bin/python -m pip install 'torch>=2.7,<3' --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -e '.[retrieval]'
```

Use a compatible wheel for your GPU/driver; see https://pytorch.org/get-started/locally/. `--device auto` chooses CUDA when PyTorch reports it available, otherwise CPU. `--device cpu` forces portable CPU execution. Explicit `--device cuda` fails clearly when CUDA is unavailable; runtime failures do not silently switch devices. Existing indexing without `--embed` and all graph commands still work without these optional packages.

Query the directory printed by indexing:

```sh
.venv/bin/archie retrieve artifacts/index/INDEX_DIRECTORY 'Where does Controller receive IService and call Run?' --top-k 5 --device auto
```

Replace `INDEX_DIRECTORY` with the actual directory name. `--top-k` accepts 1–100. JSON output includes source text, stable chunk IDs, repository-relative paths, inclusive line/column citations, cosine scores, token counts, selected/skipped chunk counts, cache statistics, extraction status, and source diagnostics. Scores rank semantic similarity; they do not prove a chunk answers the question. Empty indexes are reported explicitly. Blank or over-budget queries fail rather than being silently truncated.

The adapter uses `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions, 256-token input budget). The first use downloads model weights; embedding inference and cosine search run locally. Repository content is never sent to a remote service. Queries reload the exact model commit recorded in `embeddings.json`. Runtime versions are also part of embedding identity; changed model/runtime identity requires re-indexing. CPU and GPU share that identity, excluding the CUDA wheel suffix, although floating-point scores can differ slightly.

`--embed` stores a validated `embeddings.json` beside the other index artifacts before atomic publication. Vectors are cached in `.embedding-cache.sqlite3` in the output root, keyed by text content and model identity. Re-indexing unchanged content reuses cached document vectors; changed text embeds only missing content. Repeated identical chunks share cache entries. Cache counts refer to distinct texts, not chunk occurrences. Model files live in the output root's `.models/` directory. Keep these caches for reuse; they are not required to copy the published index to another machine. Cache files contain source-derived vectors and model files, so store them with the same care as indexes. An empty source produces an `EMPTY_SOURCE` diagnostic.

Published retrieval indexes are self-contained source snapshots. They remain queryable if the source checkout changes or moves; no live source files are read during retrieval. Existing graph queries still validate against the original checkout. Old indexes without embeddings need re-indexing with `--embed`. Source coverage remains limited to files referenced by extracted nodes/edges. Chunk IDs now include content and position; adding earlier text can shift later chunk boundaries. The reusable cache follows exact chunk text, so shifted but identical text can still be reused. Line endings are normalized to LF; columns remain UTF-16 code units.

This milestone uses exact cosine search over JSON vectors in memory. It adds no vector service, approximate search, or answer generation. Full index loading and linear scans are suitable for the current local study; larger corpora may need another search implementation. Model weights must be available locally for fully offline use (Hugging Face supports `HF_HUB_OFFLINE=1`). Model/runtime identity changes invalidate reuse; changing only CPU versus GPU does not.
