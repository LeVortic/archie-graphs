# Schema contracts

Schemas use JSON Schema Draft 2020-12. `$id` values use the repository URL and identify exact schema documents. Persisted objects reject unknown fields. Top-level contracts use `schema_version: archie.<contract>.v1` for major compatibility and optional `schema_revision` for additive revisions. A changed meaning or removed field requires a new major `vN` schema identifier.

## Contracts

- `extractor-request.schema.json`: request sent to any extractor adapter.
- `extractor-result.schema.json`: common result returned by any extractor adapter.
- `index-manifest.schema.json`: atomic index publication and artifact identity.
- `evidence-ref.schema.json`: source span, graph edge, or graph path evidence.
- `answer-record.schema.json`: answer, claims, evidence, model run, and failure state.
- `benchmark-question.schema.json`: reviewed question and fact annotations.
- `experiment-record.schema.json`: reproducible paired source/graph evaluation.
- `common.schema.json`: shared IDs, source spans, diagnostics, nodes, edges, and claims.

## Extractor port

Every adapter implements the same logical port:

```text
probe(input) -> capabilities and diagnostics
extract(request) -> ExtractorResult
cancel(operation_id) -> acknowledgement
```

`extractor-result.v1` is the interchange boundary. The Python pipeline must not import Roslyn types or assume C#-specific node kinds beyond advertised capabilities.

## Identity rules

- IDs are stable strings with a namespace prefix, such as `project:App` or `node:sha256:...`.
- Paths inside artifacts are repository-relative, use `/`, and cannot contain `..`.
- Source lines and columns are one-based and inclusive.
- `content_hash` uses lowercase `sha256:<64 hex digits>`.
- Persisted arrays use deterministic ordering defined by the producer.

## Lifecycle rules

1. Write artifacts under a temporary index directory.
2. Write `manifest.json` with `status: building` first.
3. Validate every artifact and cross-reference before publication.
4. Set `status: complete` only after validation succeeds.
5. Publish or rename the completed directory atomically.
6. On failure, write `status: failed` and preserve diagnostics.

## Validation

Run the contract tests after adding a JSON Schema validator dependency:

```bash
python -m pytest tests/test_schema_contracts.py
```
