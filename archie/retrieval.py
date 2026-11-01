"""Token-aware source chunks, content-addressed vector caching, and exact local retrieval."""
import hashlib
import json
import math
import sqlite3
from bisect import bisect_right
from pathlib import Path, PurePosixPath
from typing import Protocol

from .contracts import validate


class Embedder(Protocol):
    identity: dict
    device: str
    max_tokens: int

    def count_tokens(self, text: str) -> int: ...
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def content_hash(text):
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_source(path, text, embedder=None):
    """Keep at most 40 lines/2000 characters, shrinking to the model's token budget."""
    text = "\n".join(text.splitlines())
    starts = [0] + [offset + 1 for offset, char in enumerate(text) if char == "\n"]
    offset = 0
    while offset < len(text):
        if text[offset] == "\n":
            offset += 1
            continue
        line = bisect_right(starts, offset) - 1
        end = min(offset + 2000, len(text), starts[line + 40] if line + 40 < len(starts) else len(text))
        while embedder and embedder.count_tokens(text[offset:end]) > embedder.max_tokens:
            end = offset + (end - offset) // 2
            if end == offset:
                raise ValueError("Embedding token budget cannot fit a source character")
        body = text[offset:end]
        if body.strip():
            # Exclude trailing newlines from inclusive source spans.
            body = body.rstrip("\n")
            last = offset + len(body) - 1
            end_line = bisect_right(starts, last) - 1
            start_column = len(text[starts[line]:offset].encode("utf-16-le")) // 2 + 1
            end_column = len(text[starts[end_line]:last + 1].encode("utf-16-le")) // 2
            digest = content_hash(body)
            identity = f"{path}\0{line + 1}\0{start_column}\0{digest}"
            yield {"schema_version": "archie.source-chunk.v1", "id": "chunk:" + content_hash(identity)[7:],
                   "path": path, "start_line": line + 1, "start_column": start_column,
                   "end_line": end_line + 1, "end_column": end_column, "text": body,
                   "content_hash": digest,
                   "token_estimate": embedder.count_tokens(body) if embedder else max(1, (len(body.encode('utf-8')) + 3) // 4)}
        offset = end


def _vector(vector, dimensions):
    if (not isinstance(vector, list) or len(vector) != dimensions
            or any(type(number) not in {int, float} for number in vector)):
        raise ValueError("Invalid embedding vector or dimensions")
    try:
        norm = math.hypot(*vector)
    except OverflowError as error:
        raise ValueError("Embedding vector values are too large") from error
    if not math.isfinite(norm) or norm == 0:
        raise ValueError("Embedding vectors must have a finite nonzero norm")
    return list(vector) if math.isclose(norm, 1.0, rel_tol=1e-12) else [number / norm for number in vector]


def build_embeddings(chunks, embedder: Embedder, cache_path, source_hash, *, extraction_status="succeeded", diagnostics=()):
    model_key = content_hash(json.dumps(embedder.identity, sort_keys=True))
    dimensions = embedder.identity["dimensions"]
    by_hash = {chunk["content_hash"]: chunk["text"] for chunk in chunks}
    vectors, missing = {}, []
    if Path(cache_path).is_symlink():
        raise ValueError("Embedding cache must not be a symlink")
    with sqlite3.connect(cache_path, timeout=30) as cache:
        cache.execute("CREATE TABLE IF NOT EXISTS vectors (model TEXT, content TEXT, vector TEXT, PRIMARY KEY(model, content))")
        for digest in by_hash:
            row = cache.execute("SELECT vector FROM vectors WHERE model=? AND content=?", (model_key, digest)).fetchone()
            if row:
                try:
                    vectors[digest] = _vector(json.loads(row[0]), dimensions)
                except (ValueError, TypeError):
                    missing.append(digest)
            else:
                missing.append(digest)
        for start in range(0, len(missing), 32):
            batch = missing[start:start + 32]
            generated = embedder.embed([by_hash[digest] for digest in batch])
            if len(generated) != len(batch):
                raise ValueError("Embedding runtime returned the wrong vector count")
            for digest, vector in zip(batch, generated):
                vectors[digest] = _vector(vector, dimensions)
                cache.execute("INSERT OR REPLACE INTO vectors VALUES (?, ?, ?)",
                              (model_key, digest, json.dumps(vectors[digest], allow_nan=False)))
    artifact = {"schema_version": "archie.embeddings.v1", "model": embedder.identity,
                "device": embedder.device, "source_content_hash": source_hash,
                "records": [{"chunk_id": chunk["id"], "vector": vectors[chunk["content_hash"]]} for chunk in chunks],
                "cache": {"reused": len(by_hash) - len(missing), "embedded": len(missing)},
                "extraction_status": extraction_status, "diagnostics": list(diagnostics)}
    validate("embeddings", artifact)
    return artifact


def _artifact(index, relative):
    path = (index / relative).resolve(strict=True)
    if not path.is_relative_to(index):
        raise ValueError("Retrieval artifact escapes index directory")
    return path


def load_source_index(index):
    index = Path(index).resolve(strict=True)
    manifest = json.loads((index / "manifest.json").read_text(encoding="utf-8"))
    validate("index-manifest", manifest)
    if manifest["status"] != "complete":
        raise ValueError("Retrieval requires a complete published index")
    if "embeddings" not in manifest["artifacts"]:
        raise ValueError("Index has no embeddings; re-index with --embed")
    embeddings = json.loads(_artifact(index, manifest["artifacts"]["embeddings"]).read_text(encoding="utf-8"))
    validate("embeddings", embeddings)
    if embeddings["source_content_hash"] != manifest["source"]["content_hash"]:
        raise ValueError("Embedding content hash does not match manifest")
    chunks = {}
    with _artifact(index, manifest["artifacts"]["source_chunks"]).open(encoding="utf-8") as stream:
        for line in stream:
            chunk = json.loads(line)
            validate("source-chunk", chunk)
            path = PurePosixPath(chunk["path"])
            if "\\" in str(path) or path.is_absolute() or ".." in path.parts:
                raise ValueError("Invalid chunk source path")
            identity = f"{chunk['path']}\0{chunk['start_line']}\0{chunk['start_column']}\0{chunk['content_hash']}"
            if (chunk["id"] in chunks or content_hash(chunk["text"]) != chunk["content_hash"]
                    or chunk["id"] != "chunk:" + content_hash(identity)[7:]):
                raise ValueError("Duplicate chunk ID or invalid chunk identity/content hash")
            lines = chunk["text"].splitlines()
            width = len(lines[-1].encode("utf-16-le")) // 2
            expected_end = width + (chunk["start_column"] - 1 if len(lines) == 1 else 0)
            if (chunk["end_line"] != chunk["start_line"] + len(lines) - 1
                    or chunk["end_column"] != expected_end):
                raise ValueError("Chunk text does not match its source span")
            chunks[chunk["id"]] = chunk
    vectors = {}
    for record in embeddings["records"]:
        if record["chunk_id"] in vectors or record["chunk_id"] not in chunks:
            raise ValueError("Duplicate or unknown embedding chunk ID")
        vectors[record["chunk_id"]] = _vector(record["vector"], embeddings["model"]["dimensions"])
    if vectors.keys() != chunks.keys():
        raise ValueError("Missing chunk embeddings")
    return manifest, embeddings, chunks, vectors


def retrieve(index, query, embedder: Embedder, *, top_k=5):
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Retrieval query must not be empty")
    if type(top_k) is not int or not 1 <= top_k <= 100:
        raise ValueError("top_k must be an integer between 1 and 100")
    manifest, embeddings, chunks, vectors = load_source_index(index)
    if embedder.identity != embeddings["model"]:
        raise ValueError("Embedding model identity differs from the index; re-index with --embed")
    if embedder.count_tokens(query) > embedder.max_tokens:
        raise ValueError("Retrieval query exceeds the embedding model token limit")
    query_vectors = embedder.embed([query])
    if len(query_vectors) != 1:
        raise ValueError("Embedding runtime returned the wrong query vector count")
    vector = _vector(query_vectors[0], embedder.identity["dimensions"])
    # shortcut: exact in-memory search suits local study indexes; replace when linear scans become too slow.
    scores = [(max(-1.0, min(1.0, math.fsum(a * b for a, b in zip(vector, other)))), key)
              for key, other in vectors.items()]
    scores.sort(key=lambda item: (-item[0], item[1]))
    matches = [{"score": score, **chunks[key]} for score, key in scores[:top_k]]
    return {"index_id": manifest["index_id"], "query": query, "model": embeddings["model"],
            "device": embedder.device, "top_k": top_k, "matches": matches,
            "extraction_status": embeddings["extraction_status"],
            "source_diagnostics": embeddings["diagnostics"],
            "diagnostics": {"available_chunks": len(chunks), "selected_chunks": len(matches),
                            "skipped_chunks": max(0, len(chunks) - len(matches)),
                            "selected_tokens": sum(chunk["token_estimate"] for chunk in matches),
                            "cache": embeddings["cache"], "scoring": "cosine", "insufficient_evidence": not matches}}
