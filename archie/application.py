"""Index orchestration; extractor details remain behind the injected port."""
import json
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .contracts import validate, validate_index
from .retrieval import chunk_source, build_embeddings


class Extractor(Protocol):
    identity: dict

    def extract(self, request: dict) -> dict: ...


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def index_solution(path, output, extractor: Extractor, *, embedder=None):
    path = Path(path).resolve(strict=True)
    if path.suffix not in {".sln", ".csproj"}:
        raise ValueError("Input must be a .sln or .csproj file")
    root = path.parent
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    index_id = "index:" + uuid.uuid4().hex
    staging = Path(tempfile.mkdtemp(prefix=".building-", dir=output))
    manifest = {
        "schema_version": "archie.index-manifest.v1", "index_id": index_id,
        "status": "building", "created_at": datetime.now(timezone.utc).isoformat(),
        "source": {"path": str(path), "content_hash": "sha256:" + "0" * 64},
        "extractor": extractor.identity,
        "artifacts": {"extractor": "extractor.json", "graph": "graph.json",
                      "source_chunks": "source-chunks.jsonl", "diagnostics": "diagnostics.json"},
    }
    write_json(staging / "manifest.json", manifest)
    try:
        request = {"schema_version": "archie.extractor-request.v1",
                   "input": {"path": str(path)}, "options": {"timeout_seconds": 120}}
        validate("extractor-request", request)
        result = extractor.extract(request)
        write_json(staging / "extractor.json", result)
        validate_index(result, root)
        if Path(result["input"]["path"]).resolve() != path:
            raise ValueError("Extractor returned a different input path")
        manifest["source"]["content_hash"] = result["input"]["content_hash"]
        if {k: result["extractor"][k] for k in extractor.identity} != extractor.identity:
            raise ValueError("Extractor identity does not match the selected adapter")
        if result["status"] == "failed":
            raise ValueError("Extractor failed; inspect extractor.json diagnostics")
        write_json(staging / "graph.json", {"schema_version": "archie.graph.v1",
                   "nodes": result["nodes"], "edges": result["edges"],
                   "extractor": result["extractor"]})
        paths = sorted({item["source"]["path"] for item in result["nodes"] + result["edges"] if "source" in item})
        chunks = []
        skipped = []
        for relative in paths:
            text = (root / relative).read_text(encoding="utf-8-sig")
            source_chunks = list(chunk_source(relative, text, embedder))
            if not source_chunks:
                skipped.append(relative)
            for chunk in source_chunks:
                validate("source-chunk", chunk)
            chunks.extend(source_chunks)
        with (staging / "source-chunks.jsonl").open("w", encoding="utf-8") as stream:
            for chunk in chunks:
                stream.write(json.dumps(chunk) + "\n")
        for relative in skipped:
            result["diagnostics"].append({"code": "EMPTY_SOURCE", "severity": "info",
                "message": f"Skipped empty source: {relative}", "component": "retrieval", "recoverable": True})
        if embedder is not None:
            embeddings = build_embeddings(chunks, embedder, output / ".embedding-cache.sqlite3",
                                          result["input"]["content_hash"],
                                          extraction_status=result["status"], diagnostics=result["diagnostics"])
            write_json(staging / "embeddings.json", embeddings)
            manifest["artifacts"]["embeddings"] = "embeddings.json"
        write_json(staging / "diagnostics.json", result["diagnostics"])
        manifest["status"] = "complete"
        validate("index-manifest", manifest)
        write_json(staging / "manifest.json", manifest)
        destination = output / index_id.replace(":", "-")
        staging.rename(destination)
        return destination
    except Exception as error:
        manifest["status"] = "failed"
        manifest["error"] = {"code": "INDEX_FAILED", "severity": "error", "message": str(error),
                             "component": "index", "recoverable": False}
        write_json(staging / "manifest.json", manifest)
        raise ValueError(f"{error}; failed artifacts: {staging}") from error
