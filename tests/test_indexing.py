import json
from copy import deepcopy
from pathlib import Path

import pytest

from archie.application import index_solution
from archie.cli import ASSEMBLY, RoslynExtractor, main
from archie.contracts import validate_index
from archie.graph import load_graph, query_dependencies

ROOT = Path(__file__).parents[1]


@pytest.fixture
def fixture(tmp_path):
    value = json.loads((ROOT / "fixtures/schemas/valid/extractor-result.json").read_text())
    for item in value["nodes"] + value["edges"]:
        if "source" in item:
            span = item["source"]
            path = tmp_path / span["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text((" " * 200 + "\n") * 100)
    (tmp_path / "App.sln").write_text("fixture")
    value["input"]["path"] = str(tmp_path / "App.sln")
    return value


class FakeExtractor:
    def __init__(self, value):
        self.value = value
        self.identity = {key: value["extractor"][key] for key in ("id", "version", "interface_version")}

    def extract(self, request):
        return deepcopy(self.value)


def test_publishes_complete_index(tmp_path, fixture):
    destination = index_solution(tmp_path / "App.sln", tmp_path / "indexes", FakeExtractor(fixture))
    manifest = json.loads((destination / "manifest.json").read_text())
    assert manifest["status"] == "complete"
    assert all((destination / path).is_file() for path in manifest["artifacts"].values())
    assert not list(destination.parent.glob(".building-*"))


@pytest.mark.parametrize("damage", ["endpoint", "missing_evidence", "line", "duplicate", "escape"])
def test_rejects_invalid_evidence(tmp_path, fixture, damage):
    if damage == "endpoint":
        fixture["edges"][0]["to"] = "type:Missing"
    elif damage == "missing_evidence":
        del fixture["edges"][0]["source"]
    elif damage == "line":
        fixture["edges"][0]["source"]["end_line"] = 10000
    elif damage == "duplicate":
        fixture["nodes"].append(fixture["nodes"][0])
    else:
        outside = tmp_path.parent / "outside.cs"
        outside.write_text("outside")
        source = tmp_path / fixture["edges"][0]["source"]["path"]
        source.unlink()
        source.symlink_to(outside)
    with pytest.raises(ValueError):
        validate_index(fixture, tmp_path)


def test_failed_index_is_preserved(tmp_path, fixture):
    fixture["edges"][0]["to"] = "type:Missing"
    output = tmp_path / "indexes"
    with pytest.raises(ValueError, match="failed artifacts"):
        index_solution(tmp_path / "App.sln", output, FakeExtractor(fixture))
    manifest = json.loads(next(output.glob(".building-*/manifest.json")).read_text())
    assert manifest["status"] == "failed"
    assert manifest["error"]["code"] == "INDEX_FAILED"


def test_malformed_extractor_output_preserves_failure(tmp_path, fixture):
    class MalformedExtractor(FakeExtractor):
        def extract(self, request):
            raise json.JSONDecodeError("Malformed extractor JSON", "{", 1)

    with pytest.raises(ValueError, match="Malformed extractor JSON"):
        index_solution(tmp_path / "App.sln", tmp_path / "indexes", MalformedExtractor(fixture))
    manifest = json.loads(next((tmp_path / "indexes").glob(".building-*/manifest.json")).read_text())
    assert manifest["status"] == "failed"


def test_cli_missing_input(tmp_path, capsys):
    assert main(["index", str(tmp_path / "missing.sln")]) == 1
    assert json.loads(capsys.readouterr().err)["status"] == "failed"


@pytest.mark.skipif(not ASSEMBLY.is_file(), reason="Build the Roslyn extractor before integration tests")
def test_roslyn_fixture_end_to_end(tmp_path):
    solution = ROOT / "fixtures/csharp/Fixture.sln"
    first = index_solution(solution, tmp_path, RoslynExtractor())
    second = index_solution(solution, tmp_path, RoslynExtractor())
    a = json.loads((first / "extractor.json").read_text())
    b = json.loads((second / "extractor.json").read_text())
    assert a == b
    assert a["status"] == "succeeded", a["diagnostics"]
    assert len(a["projects"]) == 2
    assert {e["kind"] for e in a["edges"]} == {"inherits", "implements", "calls", "field_use", "constructor_use"}
    by_id = {n["id"]: n for n in a["nodes"]}
    call = next(e for e in a["edges"] if e["kind"] == "calls")
    assert by_id[call["from"]]["project_id"] != by_id[call["to"]]["project_id"]
    assert call["source"]["start_line"] == 9
    assert {"field_use", "constructor_use"} <= set(a["extractor"]["capabilities"])
    dependencies = [e for e in a["edges"] if e["kind"] in {"field_use", "constructor_use"}]
    assert {(e["kind"], by_id[e["from"]]["name"], by_id[e["to"]]["name"],
             e["source"]["start_line"]) for e in dependencies} == {
        ("field_use", "Controller", "IService", 7),
        ("constructor_use", "Controller", "IService", 8),
        ("constructor_use", "Controller", "Service", 10),
        ("constructor_use", "Controller", "Service", 11),
    }
    graph = load_graph(first)
    controller = next(n["id"] for n in a["nodes"] if n["name"] == "Controller" and n["kind"] == "type")
    service = next(n["id"] for n in a["nodes"] if n["name"] == "IService")
    assert {e["id"] for e in query_dependencies(graph, controller)["edges"]} == {e["id"] for e in dependencies}
    assert {e["kind"] for e in query_dependencies(graph, service, reverse=True)["edges"]} == {"field_use", "constructor_use", "implements"}
    lines = (ROOT / "fixtures/csharp/App/Controller.cs").read_text().splitlines()
    for edge in dependencies:
        assert by_id[edge["from"]]["project_id"] != by_id[edge["to"]]["project_id"]
        span = edge["source"]
        assert span["path"] == "App/Controller.cs"
        assert span["start_line"] == span["end_line"]
        evidence = lines[span["start_line"] - 1][span["start_column"] - 1:span["end_column"]]
        assert evidence == {7: "IService", 8: "IService", 10: "new Service()", 11: "new()"}[span["start_line"]]


@pytest.mark.skipif(not ASSEMBLY.is_file(), reason="Build the Roslyn extractor before integration tests")
def test_unresolved_call_is_diagnostic_not_edge(tmp_path):
    project = tmp_path / "Broken.csproj"
    project.write_text((ROOT / "fixtures/csharp/Core/Core.csproj").read_text())
    (tmp_path / "Broken.cs").write_text("public class Broken { public void Run() { Missing.Call(); } }\n")
    result = RoslynExtractor().extract({"schema_version": "archie.extractor-request.v1",
        "input": {"path": str(project)}, "options": {"timeout_seconds": 120}})
    validate_index(result, tmp_path)
    assert result["status"] == "partial"
    assert any(d["code"] == "UNRESOLVED_CALL" for d in result["diagnostics"])
    assert result["edges"] == []


@pytest.mark.skipif(not ASSEMBLY.is_file(), reason="Build the Roslyn extractor before integration tests")
def test_unresolved_dependencies_remain_diagnostics(tmp_path):
    project = tmp_path / "Broken.csproj"
    project.write_text((ROOT / "fixtures/csharp/Core/Core.csproj").read_text())
    (tmp_path / "Broken.cs").write_text(
        "public class Broken { Missing field; string external; public Broken(Missing value, string text) {} "
        "public object External() => new object(); public object Create() => new Missing(); }\n")
    result = RoslynExtractor().extract({"schema_version": "archie.extractor-request.v1",
        "input": {"path": str(project)}, "options": {"timeout_seconds": 120}})
    validate_index(result, tmp_path)
    assert result["status"] == "partial"
    assert {"UNRESOLVED_SYMBOL", "UNRESOLVED_CONSTRUCTOR"} <= {d["code"] for d in result["diagnostics"]}
    assert result["edges"] == []
