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


@pytest.fixture
def traversal_graph(published):
    graph = load_graph(published)
    evidence = deepcopy(next(iter(graph.edges(data=True)))[2]["source"])
    graph.clear_edges()
    graph.remove_nodes_from(list(graph))
    for node in ("A", "B", "C", "D", "X"):
        graph.add_node(node, id=node, kind="type", name=node, qualified_name=node,
                       project_id="project:" + ("one" if node == "A" else "two"))
    for source, target, key in (("A", "B", "ab1"), ("A", "B", "ab2"), ("B", "C", "bc"),
                                ("C", "A", "ca"), ("C", "C", "cc"), ("C", "D", "cd")):
        graph.add_edge(source, target, key=key, id=key, **{"from": source, "to": target},
                       kind="calls", status="extracted", confidence=1.0, source=deepcopy(evidence))
    return graph


def test_neighborhood_depth_direction_and_evidence(traversal_graph):
    from archie.graph import query_neighborhood

    graph = traversal_graph
    one = query_neighborhood(graph, "A", max_depth=1)
    two = query_neighborhood(graph, "A", max_depth=2)
    assert {e["id"] for e in one["edges"]} == {"ab1", "ab2"}
    assert {e["id"] for e in two["edges"]} == {"ab1", "ab2", "bc"}
    incoming = query_neighborhood(graph, "D", reverse=True, max_depth=2)
    assert {e["id"] for e in incoming["edges"]} == {"bc", "cc", "cd"}
    assert next(e for e in incoming["edges"] if e["id"] == "cd")["to"] == "D"
    assert all(e["source"]["path"] for e in two["edges"])
    assert len({n["project_id"] for n in two["nodes"]}) == 2
    assert not two["truncated"]
    assert len(query_neighborhood(graph, "A", max_depth=10)["edges"]) == 6
    assert query_neighborhood(graph, "X")["edges"] == []


def test_neighborhood_limits(traversal_graph):
    from archie.graph import query_neighborhood

    result = query_neighborhood(traversal_graph, "A", max_nodes=1)
    assert len(result["nodes"]) == 1 and result["edges"] == []
    assert result["truncation_reasons"] == ["max_nodes"]
    result = query_neighborhood(traversal_graph, "A", max_edges=1)
    assert len(result["edges"]) == 1 and result["truncation_reasons"] == ["max_edges"]
    assert not query_neighborhood(traversal_graph, "A", max_depth=1, max_edges=2)["truncated"]


def test_paths_match_networkx_and_retain_parallel_evidence(traversal_graph):
    import networkx as nx
    from archie.graph import query_paths

    graph = traversal_graph
    expected = {tuple(edge[2] for edge in path) for path in nx.all_simple_edge_paths(graph, "A", "D", cutoff=3)}
    result = query_paths(graph, "A", "D")
    assert {tuple(path) for path in result["paths"]} == expected == {("ab1", "bc", "cd"), ("ab2", "bc", "cd")}
    assert {e["id"] for e in result["edges"]} == {"ab1", "ab2", "bc", "cd"}
    assert all(e["source"] for e in result["edges"])
    assert not result["truncated"]
    assert query_paths(graph, "A", "D", max_depth=2)["paths"] == []
    assert query_paths(graph, "D", "A")["paths"] == []
    assert query_paths(graph, "A", "A")["paths"] == [[]]


def test_cycles_include_self_loops_without_rotations(traversal_graph):
    from archie.graph import query_cycles

    result = query_cycles(traversal_graph)
    assert {tuple(cycle) for cycle in result["cycles"]} == {("ab1", "bc", "ca"), ("ab2", "bc", "ca"), ("cc",)}
    assert not result["truncated"]
    assert query_cycles(traversal_graph, max_depth=1)["cycles"] == [["cc"]]
    acyclic = traversal_graph.copy()
    acyclic.remove_edges_from([("C", "A", "ca"), ("C", "C", "cc")])
    assert query_cycles(acyclic)["cycles"] == []


@pytest.mark.parametrize("operation", ["paths", "cycles"])
def test_search_work_node_and_result_limits(traversal_graph, operation):
    from archie.graph import query_paths, query_cycles

    def run(**limits):
        return (query_paths(traversal_graph, "A", "D", **limits) if operation == "paths"
                else query_cycles(traversal_graph, **limits))

    result = run(max_steps=1)
    assert result["search_steps"] == 1
    assert result["truncation_reasons"] == ["max_steps"]
    result = run(max_nodes=1)
    assert result["visited_nodes"] == 1 and result["truncation_reasons"] == ["max_nodes"]
    result = run(max_paths=1)
    assert len(result[operation]) == 1 and result["truncation_reasons"] == ["max_paths"]
    exact = 2 if operation == "paths" else 3
    assert not run(max_paths=exact)["truncated"]


@pytest.mark.parametrize("operation", ["neighborhood", "paths", "cycles"])
@pytest.mark.parametrize("name,value", [("max_depth", 0), ("max_depth", 11), ("max_nodes", 0),
                                        ("max_nodes", 1001), ("max_depth", True), ("max_depth", 1.5)])
def test_new_query_limit_validation(traversal_graph, operation, name, value):
    from archie.graph import query_neighborhood, query_paths, query_cycles

    with pytest.raises(ValueError):
        if operation == "neighborhood":
            query_neighborhood(traversal_graph, "A", **{name: value})
        elif operation == "paths":
            query_paths(traversal_graph, "A", "D", **{name: value})
        else:
            query_cycles(traversal_graph, **{name: value})


def test_new_cli_commands_and_errors(published, capsys):
    a, b = "type:App.CheckoutController", "type:App.CheckoutService"
    for command, symbols, field in (("neighborhood", [a], "edges"), ("paths", [a, b], "paths"),
                                    ("cycles", [], "cycles")):
        assert main(["inspect", command, str(published), *symbols]) == 0
        assert json.loads(capsys.readouterr().out)[field]
    assert main(["inspect", "neighborhood", str(published), b, "--reverse"]) == 0
    assert json.loads(capsys.readouterr().out)["direction"] == "incoming"
    for arguments in (["paths", a, "missing"], ["neighborhood", "missing"]):
        assert main(["inspect", arguments[0], str(published), *arguments[1:]]) == 1
        assert "Unknown symbol" in json.loads(capsys.readouterr().err)["error"]
    assert main(["inspect", "cycles", str(published), "--max-steps", "0"]) == 1
    assert "max_steps" in json.loads(capsys.readouterr().err)["error"]


def test_other_limit_ranges_and_empty_graph(traversal_graph):
    from archie.graph import query_neighborhood, query_paths, query_cycles

    for name, values in (("max_steps", (0, 100001, True)), ("max_paths", (0, 101, True))):
        for value in values:
            with pytest.raises(ValueError, match=name):
                query_paths(traversal_graph, "A", "D", **{name: value})
            with pytest.raises(ValueError, match=name):
                query_cycles(traversal_graph, **{name: value})
    for value in (0, 1001, True):
        with pytest.raises(ValueError, match="max_edges"):
            query_neighborhood(traversal_graph, "A", max_edges=value)
    traversal_graph.remove_nodes_from(list(traversal_graph))
    result = query_cycles(traversal_graph)
    assert result["cycles"] == [] and result["nodes"] == [] and not result["truncated"]


def test_multi_hop_results_ignore_artifact_array_order(published):
    from archie.graph import query_neighborhood, query_paths, query_cycles

    a, b = "type:App.CheckoutController", "type:App.CheckoutService"
    graph = load_graph(published)
    expected = (query_neighborhood(graph, a), query_paths(graph, a, b), query_cycles(graph))
    path = published / "extractor.json"
    value = json.loads(path.read_text())
    value["nodes"].reverse()
    value["edges"].reverse()
    path.write_text(json.dumps(value))
    graph = load_graph(published)
    assert expected == (query_neighborhood(graph, a), query_paths(graph, a, b), query_cycles(graph))


def test_cycle_search_matches_networkx_on_small_graphs(traversal_graph):
    import itertools
    import networkx as nx
    from archie.graph import query_cycles

    for mask in (0, 1, 7, 19, 31, 42, 55, 63):
        graph = traversal_graph.copy()
        graph.remove_edges_from(list(graph.edges(keys=True)))
        pairs = [(a, b) for a in ("A", "B", "C") for b in ("A", "B", "C") if a != b]
        pairs += [("B", "B")]
        for bit, (a, b) in enumerate(pairs):
            if bit == 6 or mask & (1 << bit):
                graph.add_edge(a, b, key=a+b, id=a+b, **{"from": a, "to": b}, kind="calls")
        expected = set()
        for cycle in nx.simple_cycles(graph, length_bound=3):
            start = cycle.index(min(cycle))
            cycle = cycle[start:] + cycle[:start]
            choices = [graph[a][b].keys() for a, b in zip(cycle, cycle[1:] + cycle[:1])]
            expected.update(itertools.product(*choices))
        actual = query_cycles(graph, max_paths=100)
        assert {tuple(path) for path in actual["cycles"]} == expected
        assert not actual["truncated"]
