import json
import re
import sqlite3
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import ValidationError

from archie.application import index_solution
from archie.cli import main
from archie.contracts import validate
from archie.retrieval import chunk_source, load_source_index, retrieve

ROOT = Path(__file__).parents[1]


class FakeEmbedder:
    device = "cpu"
    max_tokens = 64
    identity = {"model_id": "fake-local", "revision": "one", "runtime": "fake",
                "runtime_version": "1", "dimensions": 3, "max_tokens": 64, "normalized": True}

    def __init__(self):
        self.calls = []

    def count_tokens(self, text):
        return len(re.findall(r"\w+|[^\w\s]", text)) + 2

    def embed(self, texts):
        self.calls.extend(texts)
        return [[text.lower().count("apple"), text.lower().count("orange"), 1.0] for text in texts]


@pytest.fixture
def source(tmp_path):
    value = json.loads((ROOT / "fixtures/schemas/valid/extractor-result.json").read_text())
    value["input"]["path"] = str(tmp_path / "App.sln")
    (tmp_path / "App.sln").write_text("fixture")
    for number, node in enumerate(value["nodes"]):
        path = tmp_path / node["source"]["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        label = "apple" if number == 0 else "orange"
        path.write_text(("// " + label + " service handles requests " + " " * 200 + "\n") * 100)
    extractor = SimpleNamespace(identity={key: value["extractor"][key] for key in ("id", "version", "interface_version")},
                                extract=lambda request: deepcopy(value))
    return tmp_path, value, extractor


def test_token_chunks_have_deterministic_utf16_source_spans():
    embedder = FakeEmbedder()
    embedder.max_tokens = 8
    text = 'apple 😀 orange\r\n\r\n' + 'x ' * 2400 + '\r\nlast line\r\n'
    chunks = list(chunk_source("src/Example.cs", text, embedder))
    assert chunks == list(chunk_source("src/Example.cs", text, embedder))
    assert len(chunks) > 2
    lines = text.splitlines()
    for chunk in chunks:
        validate("source-chunk", chunk)
        assert chunk["token_estimate"] <= 8
        selected = lines[chunk["start_line"] - 1:chunk["end_line"]]
        selected[0] = selected[0].encode("utf-16-le")[(chunk["start_column"] - 1) * 2:].decode("utf-16-le")
        last_width = chunk["end_column"] - (chunk["start_column"] - 1 if len(selected) == 1 else 0)
        selected[-1] = selected[-1].encode("utf-16-le")[:last_width * 2].decode("utf-16-le")
        assert "\n".join(selected) == chunk["text"]
    assert list(chunk_source("empty.cs", " \n\n")) == []


def test_reindex_reuses_vectors_and_changes_only_affected_content(source):
    root, value, extractor = source
    embedder = FakeEmbedder()
    output = root / "indexes"
    first = index_solution(root / "App.sln", output, extractor, embedder=embedder)
    first_calls = set(embedder.calls)
    assert first_calls
    embedder.calls.clear()
    second = index_solution(root / "App.sln", output, extractor, embedder=embedder)
    assert embedder.calls == []
    a = load_source_index(first)
    b = load_source_index(second)
    assert a[2] == b[2] and a[3] == b[3]
    assert b[1]["cache"]["embedded"] == 0
    path = root / value["nodes"][0]["source"]["path"]
    path.write_text(path.read_text().replace("apple", "peach", 1))
    third = index_solution(root / "App.sln", output, extractor, embedder=embedder)
    assert embedder.calls and all("peach" in text for text in embedder.calls)
    assert load_source_index(third)[1]["cache"]["reused"] > 0
    embedder.calls.clear()
    embedder.identity = dict(embedder.identity, revision="two")
    index_solution(root / "App.sln", output, extractor, embedder=embedder)
    assert embedder.calls


def test_retrieval_ranking_citations_device_portability_and_validation(source):
    root, _, extractor = source
    embedder = FakeEmbedder()
    embedder.device = "cuda"
    index = index_solution(root / "App.sln", root / "indexes", extractor, embedder=embedder)
    embedder.device = "cpu"
    first = retrieve(index, "apple", embedder, top_k=3)
    assert first == retrieve(index, "apple", embedder, top_k=3)
    assert first["matches"] and all("apple" in chunk["text"] for chunk in first["matches"])
    assert all(chunk["path"].endswith("CheckoutController.cs") for chunk in first["matches"])
    assert first["device"] == "cpu" and first["diagnostics"]["selected_tokens"] > 0
    assert len(first["matches"]) == 3
    # Retrieval is backed by snapshots, so copied indexes need no live source checkout.
    for path in (root / "src").rglob("*.cs"):
        path.unlink()
    assert retrieve(index, "apple", embedder, top_k=3)["matches"] == first["matches"]
    for query, top_k in [("", 5), ("apple", 0), ("apple", 101), ("apple", True), ("word " * 100, 5)]:
        with pytest.raises(ValueError):
            retrieve(index, query, embedder, top_k=top_k)
    embedder.identity = dict(embedder.identity, revision="other")
    with pytest.raises(ValueError, match="identity"):
        retrieve(index, "apple", embedder)


@pytest.mark.parametrize("damage", ["nan", "zero", "dimensions", "count"])
def test_embedding_failures_preserve_failed_index(source, damage):
    root, _, extractor = source
    embedder = FakeEmbedder()
    embedder.embed = lambda texts: ([] if damage == "count" else
                                   [[float("nan"), 0, 1] if damage == "nan" else [0, 0, 0] if damage == "zero"
                                    else [1, 0] for text in texts])
    with pytest.raises(ValueError):
        index_solution(root / "App.sln", root / "indexes", extractor, embedder=embedder)
    manifest = json.loads(next((root / "indexes").glob(".building-*/manifest.json")).read_text())
    assert manifest["status"] == "failed"
    assert not list((root / "indexes").glob("index-*"))


@pytest.mark.parametrize("damage", ["vector", "duplicate", "missing", "unknown", "hash", "span", "path", "escape"])
def test_retrieval_rejects_corrupt_artifacts(source, damage):
    root, _, extractor = source
    index = index_solution(root / "App.sln", root / "indexes", extractor, embedder=FakeEmbedder())
    path = index / "embeddings.json"
    value = json.loads(path.read_text())
    if damage == "vector":
        value["records"][0]["vector"] = [0, 0, 0]
    elif damage == "duplicate":
        value["records"].append(value["records"][0])
    elif damage == "missing":
        value["records"].pop()
    elif damage == "unknown":
        value["records"][0]["chunk_id"] = "chunk:" + "0" * 64
    elif damage == "hash":
        value["source_content_hash"] = "sha256:" + "0" * 64
    elif damage == "escape":
        manifest_path = index / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["artifacts"]["embeddings"] = "../outside.json"
        manifest_path.write_text(json.dumps(manifest))
    else:
        chunks_path = index / "source-chunks.jsonl"
        chunks = [json.loads(line) for line in chunks_path.read_text().splitlines()]
        if damage == "span":
            chunks[0]["end_line"] += 1
        else:
            chunks[0]["path"] = "../outside.cs"
        chunks_path.write_text("\n".join(json.dumps(chunk) for chunk in chunks) + "\n")
    path.write_text(json.dumps(value))
    with pytest.raises((ValueError, ValidationError)):
        load_source_index(index)


def test_cli_index_and_retrieve_with_fake_runtime(source, monkeypatch, capsys):
    root, _, extractor = source
    embedder = FakeEmbedder()
    monkeypatch.setattr("archie.cli.RoslynExtractor", lambda: extractor)
    monkeypatch.setattr("archie.cli.SentenceEmbedder", lambda **kwargs: embedder)
    assert main(["index", str(root / "App.sln"), "--output", str(root / "indexes"), "--embed", "--device", "cpu"]) == 0
    index = json.loads(capsys.readouterr().out)["path"]
    assert main(["retrieve", index, "apple", "--top-k", "2", "--device", "cpu"]) == 0
    assert len(json.loads(capsys.readouterr().out)["matches"]) == 2
    assert main(["retrieve", index, "apple", "--top-k", "0"]) == 1
    assert json.loads(capsys.readouterr().err)["status"] == "failed"


def test_no_embeddings_error_and_corrupt_cache_recovery(source):
    root, _, extractor = source
    index = index_solution(root / "App.sln", root / "indexes", extractor)
    with pytest.raises(ValueError, match="--embed"):
        load_source_index(index)
    embedder = FakeEmbedder()
    index_solution(root / "App.sln", root / "indexes", extractor, embedder=embedder)
    with sqlite3.connect(root / "indexes/.embedding-cache.sqlite3") as cache:
        cache.execute("UPDATE vectors SET vector='[0,0,0]'")
    embedder.calls.clear()
    index_solution(root / "App.sln", root / "indexes", extractor, embedder=embedder)
    assert embedder.calls


@pytest.mark.parametrize("available,device,expected", [(True, "auto", "cuda"), (False, "auto", "cpu"),
                                                        (True, "cpu", "cpu")])
def test_sentence_adapter_resolves_public_revision_and_device(monkeypatch, available, device, expected):
    import sys
    from archie.embeddings import SentenceEmbedder

    captured = {}
    model = SimpleNamespace(max_seq_length=64, get_sentence_embedding_dimension=lambda: 3,
                            tokenizer=lambda text, **kwargs: {"input_ids": list(range(len(text)))},
                            encode=lambda texts, **kwargs: SimpleNamespace(tolist=lambda: [[1, 0, 0] for _ in texts]))

    def factory(model_id, **kwargs):
        captured.update(kwargs)
        return model

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: available)))
    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=factory))
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(
        hf_hub_download=lambda *args, **kwargs: "/cache/snapshots/" + "a" * 40 + "/config.json"))
    monkeypatch.setattr("archie.embeddings.version", lambda name: "1.0")
    adapter = SentenceEmbedder(device=device)
    assert adapter.device == expected and captured["device"] == expected
    assert adapter.identity["revision"] == "a" * 40 and captured["revision"] == "a" * 40
    assert captured["trust_remote_code"] is False
    with pytest.raises(ValueError, match="token limit"):
        adapter.embed(["x" * 100])
    if not available:
        with pytest.raises(ValueError, match="CUDA is unavailable"):
            SentenceEmbedder(device="cuda")
