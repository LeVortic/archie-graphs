import json
from copy import deepcopy
from pathlib import Path

import networkx as nx
import pytest
from jsonschema import ValidationError

from archie.answering import answer_graph, answer_source
from archie.cli import main
from archie.contracts import validate
from archie.graph_evidence import build_graph_context, clipped_excerpt, validate_graph_context, LIMITS
from archie.retrieval import chunk_source

ROOT = Path(__file__).parents[1]


class RecordingModel:
    identity = {"model_id": "fake-qwen", "revision": "test", "runtime_version": "fake:1",
                "device": "cpu", "dtype": "float32"}
    def __init__(self):
        self.calls = []
        self.bad_citation = False
    def count_tokens(self, messages):
        return (len(json.dumps(messages)) + 3) // 4
    def complete(self, messages, **settings):
        self.calls.append((messages, settings))
        allowed = settings["response_schema"]["properties"]["claims"]["items"]["properties"]["evidence_ids"]["items"]["enum"]
        value = {"abstain": False, "claims": [{"text": "Controller has an extracted dependency.",
                    "evidence_ids": ["evidence:999" if self.bad_citation else allowed[-1]]}]}
        return {"text": json.dumps(value), "input_tokens": self.count_tokens(messages), "output_tokens": 20,
                "finish_reason": "stop", "latency_ms": 1}


@pytest.fixture
def graph_data():
    value = json.loads((ROOT / "fixtures/schemas/valid/extractor-result.json").read_text())
    graph = nx.MultiDiGraph(index_id="index:fixture", extractor=value["extractor"],
                            extraction_status="succeeded", diagnostics=[])
    nodes = deepcopy(value["nodes"])
    base = {**deepcopy(nodes[1]), "id": "type:Core.Base", "name": "Base", "qualified_name": "Core.Base",
            "project_id": "project:Core", "source": {**nodes[1]["source"], "path": "src/Core/Base.cs"}}
    nodes.append(base)
    for node in nodes:
        graph.add_node(node["id"], **node)
    a, b, c = [node["id"] for node in nodes]
    first = deepcopy(value["edges"][0])
    second = {**deepcopy(first), "id": "edge:inherits", "from": b, "to": c, "kind": "inherits",
              "source": {**first["source"], "path": nodes[1]["source"]["path"], "start_line": 2, "end_line": 2}}
    parallel = {**deepcopy(first), "id": "edge:field", "kind": "field_use"}
    for edge in [first, parallel, second]:
        graph.add_edge(edge["from"], edge["to"], key=edge["id"], **edge)
    chunks = {}
    for node in nodes:
        text = ("// indexed source " + " " * 180 + "\n") * 25
        chunks.update({chunk["id"]: chunk for chunk in chunk_source(node["source"]["path"], text)})
    matches = [chunk for chunk in chunks.values() if chunk["path"] == nodes[0]["source"]["path"]][:1]
    retrieved = {"index_id": "index:fixture", "query": "CheckoutController dependencies", "matches": matches,
                 "model": {"model_id": "fake-embedding"}, "extraction_status": "succeeded", "source_diagnostics": []}
    return graph, retrieved, chunks


def test_graph_context_has_cross_project_multi_hop_parallel_evidence(graph_data):
    graph, retrieved, chunks = graph_data
    context = build_graph_context(graph, retrieved, chunks)
    validate_graph_context(context)
    paths = {tuple(edge["id"] for edge in path["edges"]) for path in context["paths"]}
    assert len(paths) == 4
    assert ("edge:field", "edge:inherits") in paths
    assert context["extractor"] == graph.graph["extractor"]
    assert context["diagnostics"]["seed_node_ids"] == ["type:App.CheckoutController"]
    assert not context["diagnostics"]["truncated"]
    for path in context["paths"]:
        assert all(chunk["id"] in chunks for chunk in path["source_chunks"])
        assert len(path["nodes"]) == len(path["edges"]) + 1
    two = next(path for path in context["paths"] if len(path["edges"]) == 2)
    assert two["nodes"][-1]["project_id"] == "project:Core"
    assert two["edges"][-1]["source"]["path"] == "src/App/CheckoutService.cs"


def test_context_is_deterministic_and_cycles_stop_at_depth(graph_data):
    graph, retrieved, chunks = graph_data
    expected = build_graph_context(graph, retrieved, chunks)
    shuffled = nx.MultiDiGraph(**graph.graph)
    shuffled.add_nodes_from(reversed(list(graph.nodes(data=True))))
    shuffled.add_edges_from(reversed(list(graph.edges(keys=True, data=True))))
    assert build_graph_context(shuffled, retrieved, dict(reversed(list(chunks.items())))) == expected
    edge = deepcopy(next(iter(graph.edges(data=True)))[2])
    a, b = edge["from"], edge["to"]
    graph.add_edge(b, a, key="edge:back", **{**edge, "id": "edge:back", "from": b, "to": a})
    result = build_graph_context(graph, retrieved, chunks)
    assert all(len(path["edges"]) <= 2 for path in result["paths"])
    assert any(path["nodes"][0]["id"] == path["nodes"][-1]["id"] for path in result["paths"])


def test_graph_context_limits_empty_seeds_missing_snapshots_and_index_mismatch(graph_data):
    graph, retrieved, chunks = graph_data
    assert build_graph_context(graph, {**retrieved, "matches": []}, chunks)["paths"] == []
    unbacked = build_graph_context(graph, retrieved, {})
    assert unbacked["paths"] == [] and unbacked["diagnostics"]["skipped_unbacked_edges"] == 2
    with pytest.raises(ValueError, match="same index"):
        build_graph_context(graph, {**retrieved, "index_id": "index:other"}, chunks)
    node = deepcopy(next(iter(graph.nodes(data=True)))[1])
    edge = deepcopy(next(iter(graph.edges(data=True)))[2])
    for number in range(40):
        key = f"type:Extra{number:02}"
        graph.add_node(key, **{**node, "id": key, "name": f"Extra{number}"})
        graph.add_edge(edge["from"], key, key=f"edge:extra{number:02}",
                       **{**edge, "id": f"edge:extra{number:02}", "to": key})
    context = build_graph_context(graph, retrieved, chunks)
    assert len(context["paths"]) <= LIMITS["max_paths"]
    assert context["diagnostics"]["truncated"]
    assert len(context["diagnostics"]["seed_node_ids"]) <= 5


def test_clipped_excerpts_keep_utf16_and_cross_chunk_spans():
    chunks = list(chunk_source("Example.cs", "q" * 1999 + "😀B\nCD"))
    span = {"path": "Example.cs", "start_line": 1, "start_column": 2000, "end_line": 2, "end_column": 2}
    first, second = [clipped_excerpt(span, chunk) for chunk in chunks]
    assert first["text"] == "😀" and first["end_column"] == 2001
    assert second["text"] == "B\nCD" and second["start_column"] == 2002


@pytest.mark.parametrize("damage", ["direction", "unbacked", "inferred", "disconnected", "duplicate"])
def test_invalid_graph_evidence_is_rejected_before_generation(graph_data, damage):
    graph, retrieved, chunks = graph_data
    context = build_graph_context(graph, retrieved, chunks)
    if damage == "direction":
        context["paths"][0]["edges"][0]["from"] = "type:Missing"
    elif damage == "unbacked":
        context["paths"][0]["source_chunks"] = []
    elif damage == "inferred":
        context["paths"][0]["edges"][0]["status"] = "inferred"
    elif damage == "disconnected":
        context["paths"][0]["nodes"].pop()
    else:
        context["paths"].append(deepcopy(context["paths"][0]))
    with pytest.raises((ValueError, ValidationError)):
        validate_graph_context(context)
    model = RecordingModel()
    result = answer_graph(retrieved, "Dependencies?", model, context)
    assert result["status"] == "failed" and not model.calls


def test_graph_answer_budget_citations_metadata_and_source_preservation(graph_data):
    graph, retrieved, chunks = graph_data
    context = build_graph_context(graph, retrieved, chunks)
    original = deepcopy(context)
    model = RecordingModel()
    source = answer_source(retrieved, "Dependencies?", model, context_budget=4096)
    result = answer_graph(retrieved, "Dependencies?", model, context, context_budget=4096)
    validate("answer-record", result)
    assert result["status"] == "succeeded" and result["mode"] == "graph"
    assert result["run"]["context_budget"] == source["run"]["context_budget"] == 4096
    assert result["run"]["context_tokens"] <= 4096
    assert result["run"]["model_revision"] == source["run"]["model_revision"]
    assert result["run"]["max_new_tokens"] == source["run"]["max_new_tokens"]
    assert any(item["kind"] == "graph_path" for item in result["evidence"])
    assert result["claims"][0]["support_status"] == "uncertain"
    assert "Extracted graph paths" in model.calls[-1][0][1]["content"]
    assert "statically resolved" in model.calls[-1][0][0]["content"]
    for path in result["graph_context"]["paths"]:
        evidence = next(item for item in result["evidence"] if item["id"] == path["evidence_id"])
        assert evidence["edge_ids"] == [edge["id"] for edge in path["edges"]]
        assert evidence["node_ids"] == [node["id"] for node in path["nodes"]]
    assert context == original
    model.bad_citation = True
    assert answer_graph(retrieved, "Dependencies?", model, context)["status"] == "failed"


def test_context_truncation_fallback_and_empty_abstention(graph_data):
    graph, retrieved, chunks = graph_data
    context = build_graph_context(graph, retrieved, chunks)
    model = RecordingModel()
    result = answer_graph(retrieved, "Dependencies?", model, context, context_budget=900)
    assert result["status"] == "succeeded" and result["run"]["context_tokens"] <= 900
    assert result["run"]["truncated"]
    assert "context_budget" in result["graph_context"]["diagnostics"]["truncation_reasons"]
    context["paths"] = []
    assert answer_graph(retrieved, "Dependencies?", model, context)["status"] == "succeeded"
    retrieved["matches"] = []
    model.calls.clear()
    result = answer_graph(retrieved, "Dependencies?", model, context)
    assert result["claims"] == [] and not model.calls and "Insufficient" in result["answer"]


def test_graph_ask_cli_json_text_and_index_validation(graph_data, monkeypatch, capsys, tmp_path):
    graph, retrieved, chunks = graph_data
    model = RecordingModel()
    monkeypatch.setattr("archie.cli.load_source_index", lambda path: (None, {"model": {"revision": "test"}}, chunks, None))
    monkeypatch.setattr("archie.cli.SentenceEmbedder", lambda **kwargs: object())
    monkeypatch.setattr("archie.cli.retrieve", lambda *args, **kwargs: retrieved)
    monkeypatch.setattr("archie.cli.QwenModel", lambda **kwargs: model)
    monkeypatch.setattr("archie.cli.load_graph", lambda path: graph)
    args = ["ask", str(tmp_path), "Dependencies?", "--mode", "graph"]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "graph"
    assert main(args + ["--format", "text"]) == 0
    text = capsys.readouterr().out
    assert "Graph path:" in text and "src/" in text
    graph.graph["index_id"] = "index:other"
    assert main(args) == 1
    assert "same index" in json.loads(capsys.readouterr().err)["error"]


def test_named_multi_hop_path_precedes_high_degree_neighborhood(graph_data):
    graph, retrieved, chunks = graph_data
    retrieved["query"] = "What path connects App.CheckoutController to Core.Base?"
    retrieved["matches"] += [chunk for chunk in chunks.values() if chunk["path"] == "src/Core/Base.cs"][:1]
    original = deepcopy(graph.nodes["type:App.CheckoutController"])
    edge = deepcopy(graph.edges["type:App.CheckoutController", "type:App.CheckoutService", "edge:field"])
    for number in range(40):
        key = f"type:Noise{number:02}"
        graph.add_node(key, **{**original, "id": key, "name": f"Noise{number}", "qualified_name": f"Noise{number}"})
        graph.add_edge(edge["from"], key, key=f"edge:noise{number}",
                       **{**edge, "id": f"edge:noise{number}", "to": key})
    context = build_graph_context(graph, retrieved, chunks)
    first = context["paths"][0]
    assert len(first["edges"]) == 2 and first["nodes"][-1]["id"] == "type:Core.Base"
    assert len(context["paths"]) <= 20
