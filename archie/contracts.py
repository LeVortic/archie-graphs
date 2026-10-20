"""Validate interchange records and source-backed cross-references."""
import json
from pathlib import Path, PurePosixPath

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"


def validate(name, value):
    registry = Registry()
    for path in SCHEMAS.glob("*.json"):
        schema = json.loads(path.read_text())
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text())
    Draft202012Validator(schema, registry=registry, format_checker=FormatChecker()).validate(value)


def validate_index(value, root):
    validate("extractor-result", value)
    projects = {p["id"] for p in value["projects"]}
    nodes = {n["id"] for n in value["nodes"]}
    if len(projects) != len(value["projects"]) or len(nodes) != len(value["nodes"]):
        raise ValueError("Duplicate project or node ID")
    if len({e["id"] for e in value["edges"]}) != len(value["edges"]):
        raise ValueError("Duplicate edge ID")
    for node in value["nodes"]:
        if node["project_id"] not in projects:
            raise ValueError("Node references an unknown project")
    for edge in value["edges"]:
        if edge["from"] not in nodes or edge["to"] not in nodes:
            raise ValueError("Edge references an unknown node")
        if edge["status"] != "extracted" or "source" not in edge:
            raise ValueError("Only source-backed extracted edges may enter the index")
    for item in value["nodes"] + value["edges"] + value["diagnostics"]:
        if "source" not in item:
            continue
        span = item["source"]
        path = PurePosixPath(span["path"])
        target = (root / str(path)).resolve()
        if "\\" in str(path) or path.is_absolute() or ".." in path.parts or not target.is_relative_to(root):
            raise ValueError("Source path escapes repository")
        lines = target.read_text(encoding="utf-8-sig").splitlines()
        start = (span["start_line"], span["start_column"])
        end = (span["end_line"], span["end_column"])
        if start > end or end[0] > len(lines):
            raise ValueError("Invalid source line range")
        for line, column in (start, end):
            # Roslyn measures columns in UTF-16 code units.
            width = len(lines[line - 1].encode("utf-16-le")) // 2
            if column > max(1, width):
                raise ValueError("Invalid source column")
