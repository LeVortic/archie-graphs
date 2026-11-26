"""Validate interchange records and source-backed cross-references."""
import json
import math
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


def validate_index(value, root=None, *, snapshots=None):
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
    sources = {} if snapshots is None else snapshots
    lines_by_path = {}
    for item in value["nodes"] + value["edges"] + value["diagnostics"]:
        if "source" not in item:
            continue
        span = item["source"]
        path = PurePosixPath(span["path"])
        if "\\" in str(path) or path.is_absolute() or ".." in path.parts:
            raise ValueError("Source path escapes repository")
        relative = str(path)
        if relative not in lines_by_path:
            if snapshots is None:
                target = (root / relative).resolve()
                if not target.is_relative_to(root):
                    raise ValueError("Source path escapes repository")
                sources[relative] = target.read_text(encoding="utf-8-sig")
            if not isinstance(sources.get(relative), str):
                raise ValueError(f"Missing or invalid source snapshot: {relative}")
            lines_by_path[relative] = sources[relative].splitlines()
        lines = lines_by_path[relative]
        start = (span["start_line"], span["start_column"])
        end = (span["end_line"], span["end_column"])
        if start > end or end[0] > len(lines):
            raise ValueError("Invalid source line range")
        for line, column in (start, end):
            # Roslyn measures columns in UTF-16 code units.
            width = len(lines[line - 1].encode("utf-16-le")) // 2
            if column > max(1, width):
                raise ValueError("Invalid source column")
    return sources


def validate_generation_limits(max_new_tokens, timeout_seconds):
    if type(max_new_tokens) is not int or not 1 <= max_new_tokens <= 4096:
        raise ValueError("max_new_tokens must be between 1 and 4096")
    if type(timeout_seconds) not in {int, float} or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 3600:
        raise ValueError("timeout_seconds must be positive and at most 3600")
