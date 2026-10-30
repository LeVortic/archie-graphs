import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import ValidationError

from archie.application import index_solution
from archie.cli import main
from archie.graph import load_graph, query_dependencies

ROOT = Path(__file__).parents[1]


@pytest.fixture
def published(tmp_path):
    result = json.loads((ROOT / "fixtures/schemas/valid/extractor-result.json").read_text())
    result["input"]["path"] = str(tmp_path / "App.sln")
    (tmp_path / "App.sln").write_text("fixture")
    for node in result["nodes"]:
        path = tmp_path / node["source"]["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text((" " * 100 + "\n") * 30)
    edge = result["edges"][0]
    result["edges"] += [dict(edge, id="edge:field", kind="field_use"),
                        dict(edge, id="edge:cycle", **{"from": edge["to"], "to": edge["from"]})]
    isolated = dict(result["nodes"][0], id="type:App.Isolated", name="Isolated")
    result["nodes"].append(isolated)
    adapter = SimpleNamespace(identity={key: result["extractor"][key]
                                       for key in ("id", "version", "interface_version")},
                              extract=lambda request: deepcopy(result))
    return index_solution(tmp_path / "App.sln", tmp_path / "indexes", adapter)


def test_parallel_edges_reverse_direction_and_evidence(published):
    graph = load_graph(published)
    a, b = "type:App.CheckoutController", "type:App.CheckoutService"
    outgoing = query_dependencies(graph, a)
    incoming = query_dependencies(graph, b, reverse=True)
    assert len(outgoing["edges"]) == 2
    assert outgoing["edges"] == incoming["edges"]
    assert {edge["kind"] for edge in outgoing["edges"]} == {"field_use", "constructor_use"}
    assert all(edge["from"] == a and edge["to"] == b for edge in incoming["edges"])
    original = json.loads((published / "extractor.json").read_text())
    assert all(edge in original["edges"] for edge in outgoing["edges"])
    assert outgoing["extractor"] == original["extractor"]
    assert {node["id"] for node in outgoing["nodes"]} == {a, b}


def test_limits_empty_results_cycles_and_stable_order(published):
    graph = load_graph(published)
    symbol = "type:App.CheckoutController"
    limited = query_dependencies(graph, symbol, limit=1)
    assert len(limited["edges"]) == 1 and limited["truncated"]
    assert not query_dependencies(graph, symbol, limit=2)["truncated"]
    assert not query_dependencies(graph, symbol, limit=1000)["truncated"]
    assert len(query_dependencies(graph, symbol, reverse=True)["edges"]) == 1
    empty = query_dependencies(graph, "type:App.Isolated")
    assert empty["edges"] == [] and not empty["truncated"]
    assert len(empty["nodes"]) == 1
    path = published / "extractor.json"
    value = json.loads(path.read_text())
    value["nodes"].reverse()
    value["edges"].reverse()
    path.write_text(json.dumps(value))
    assert limited == query_dependencies(load_graph(published), symbol, limit=1)


@pytest.mark.parametrize("limit", [0, -1, 1001, True, 1.5])
def test_invalid_limits(published, limit):
    with pytest.raises(ValueError, match="Limit"):
        query_dependencies(load_graph(published), "type:App.Isolated", limit=limit)


def test_cli_success_and_unknown_symbol(published, capsys):
    assert main(["inspect", "dependencies", str(published), "type:App.CheckoutController", "--limit", "1"]) == 0
    assert json.loads(capsys.readouterr().out)["truncated"]
    assert main(["inspect", "dependents", str(published), "type:App.CheckoutService"]) == 0
    assert json.loads(capsys.readouterr().out)["direction"] == "incoming"
    assert main(["inspect", "dependencies", str(published), "type:Missing"]) == 1
    assert "Unknown symbol" in json.loads(capsys.readouterr().err)["error"]


@pytest.mark.parametrize("damage", ["building", "failed", "escape", "symlink", "endpoint", "duplicate", "evidence", "hash", "identity", "schema", "extraction_failed"])
def test_loader_rejects_invalid_indexes(published, damage):
    manifest_path = published / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    path = published / "extractor.json"
    value = json.loads(path.read_text())
    if damage in {"building", "failed"}:
        manifest["status"] = damage
    elif damage == "escape":
        manifest["artifacts"]["extractor"] = "../extractor.json"
    elif damage == "symlink":
        outside = published.parent / "outside.json"
        outside.write_text(json.dumps(value))
        path.unlink()
        path.symlink_to(outside)
    elif damage == "endpoint":
        value["edges"][0]["to"] = "type:Missing"
    elif damage == "duplicate":
        value["edges"].append(value["edges"][0])
    elif damage == "evidence":
        del value["edges"][0]["source"]
    elif damage == "extraction_failed":
        value["status"] = "failed"
    elif damage == "hash":
        manifest["source"]["content_hash"] = "sha256:" + "0" * 64
    elif damage == "identity":
        manifest["extractor"]["id"] = "other"
    else:
        value["schema_version"] = "archie.extractor-result.v0"
    manifest_path.write_text(json.dumps(manifest))
    if damage != "symlink":
        path.write_text(json.dumps(value))
    with pytest.raises((ValueError, ValidationError)):
        load_graph(published)


def test_partial_extraction_is_visible_and_cli_schema_errors_are_json(published, capsys):
    path = published / "extractor.json"
    value = json.loads(path.read_text())
    value["status"] = "partial"
    value["diagnostics"] = [{"code": "INCOMPLETE", "severity": "warning", "component": "fake",
                             "message": "Partial fixture", "recoverable": True}]
    path.write_text(json.dumps(value))
    result = query_dependencies(load_graph(published), "type:App.Isolated")
    assert result["extraction_status"] == "partial"
    assert result["diagnostics"] == value["diagnostics"]
    value["status"] = "invalid"
    path.write_text(json.dumps(value))
    assert main(["inspect", "dependencies", str(published), "type:App.Isolated"]) == 1
    assert json.loads(capsys.readouterr().err)["status"] == "failed"
