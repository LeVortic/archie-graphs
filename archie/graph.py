"""Evidence-preserving graphs and bounded dependency queries."""
import json
from itertools import islice
from pathlib import Path

import networkx as nx

from .contracts import validate, validate_index


def load_graph(index):
    index = Path(index).resolve(strict=True)
    manifest = json.loads((index / "manifest.json").read_text(encoding="utf-8"))
    validate("index-manifest", manifest)
    if manifest["status"] != "complete":
        raise ValueError("Queries require a complete published index")
    artifact = (index / manifest["artifacts"]["extractor"]).resolve(strict=True)
    if not artifact.is_relative_to(index):
        raise ValueError("Extractor artifact escapes index directory")
    result = json.loads(artifact.read_text(encoding="utf-8"))
    validate("extractor-result", result)
    if result["status"] == "failed":
        raise ValueError("Cannot query a failed extraction")
    if result["input"]["content_hash"] != manifest["source"]["content_hash"]:
        raise ValueError("Extractor content hash does not match manifest")
    if {key: result["extractor"][key] for key in manifest["extractor"]} != manifest["extractor"]:
        raise ValueError("Extractor identity does not match manifest")
    root = Path(result["input"]["path"]).resolve().parent
    validate_index(result, root)
    graph = nx.MultiDiGraph(index_id=manifest["index_id"], extractor=result["extractor"],
                            extraction_status=result["status"], diagnostics=result["diagnostics"])
    for node in sorted(result["nodes"], key=lambda item: item["id"]):
        graph.add_node(node["id"], **node)
    for edge in sorted(result["edges"], key=lambda item: (item["from"], item["to"], item["id"])):
        graph.add_edge(edge["from"], edge["to"], key=edge["id"], **edge)
    return graph


def query_dependencies(graph, symbol, *, reverse=False, limit=100):
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("Limit must be an integer between 1 and 1000")
    if symbol not in graph:
        raise ValueError(f"Unknown symbol ID: {symbol}")
    incident = graph.in_edges if reverse else graph.out_edges
    edges = [dict(data) for _, _, data in islice(incident(symbol, data=True), limit + 1)]
    truncated = len(edges) > limit
    edges = edges[:limit]
    nodes = {symbol} | {edge[end] for edge in edges for end in ("from", "to")}
    return {"index_id": graph.graph["index_id"], "symbol_id": symbol,
            "direction": "incoming" if reverse else "outgoing", "limit": limit,
            "truncated": truncated, "nodes": [dict(graph.nodes[node]) for node in sorted(nodes)],
            "edges": edges, "extractor": graph.graph["extractor"],
            "extraction_status": graph.graph["extraction_status"],
            "diagnostics": graph.graph["diagnostics"]}


def _check_limit(name, value, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be an integer between 1 and {maximum}")


def _result(graph, nodes, edges, reasons, **details):
    return {"index_id": graph.graph["index_id"],
            "nodes": [dict(graph.nodes[node]) for node in sorted(nodes)],
            "edges": sorted(edges, key=lambda edge: edge["id"]),
            "truncated": bool(reasons), "truncation_reasons": sorted(reasons),
            "extractor": graph.graph["extractor"],
            "extraction_status": graph.graph["extraction_status"],
            "diagnostics": graph.graph["diagnostics"], **details}


def query_neighborhood(graph, symbol, *, reverse=False, max_depth=2, max_nodes=100, max_edges=1000):
    """Return outgoing or incoming breadth-first evidence within the requested depth."""
    from collections import deque

    for name, value, maximum in (("max_depth", max_depth, 10), ("max_nodes", max_nodes, 1000),
                                 ("max_edges", max_edges, 1000)):
        _check_limit(name, value, maximum)
    if symbol not in graph:
        raise ValueError(f"Unknown symbol ID: {symbol}")
    nodes, edges, reasons = {symbol}, [], set()
    pending = deque([(symbol, 0)])
    incident = graph.in_edges if reverse else graph.out_edges
    while pending and not reasons:
        node, depth = pending.popleft()
        if depth == max_depth:
            continue
        for source, target, data in incident(node, data=True):
            neighbor = source if reverse else target
            if len(edges) == max_edges:
                reasons.add("max_edges")
                break
            if neighbor not in nodes:
                if len(nodes) == max_nodes:
                    reasons.add("max_nodes")
                    break
                nodes.add(neighbor)
                pending.append((neighbor, depth + 1))
            edges.append(dict(data))
    return _result(graph, nodes, edges, reasons, symbol_id=symbol,
                   direction="incoming" if reverse else "outgoing",
                   limits={"max_depth": max_depth, "max_nodes": max_nodes, "max_edges": max_edges})


def _search_paths(graph, source, target, *, max_depth, max_nodes, max_paths, max_steps):
    """Bound edge-distinct simple-path search, including work between results."""
    for name, value, maximum in (("max_depth", max_depth, 10), ("max_nodes", max_nodes, 1000),
                                 ("max_paths", max_paths, 100), ("max_steps", max_steps, 100000)):
        _check_limit(name, value, maximum)
    for symbol in (source, target):
        if symbol is not None and symbol not in graph:
            raise ValueError(f"Unknown symbol ID: {symbol}")
    cycles = source is None
    found, reasons, visited = [], set(), set()
    steps = 0

    def visit(node):
        if node not in visited:
            if len(visited) == max_nodes:
                reasons.add("max_nodes")
                return False
            visited.add(node)
        return True

    def walk(start, node, ancestors, path):
        nonlocal steps
        if len(path) == max_depth or reasons:
            return
        for _, neighbor, data in graph.out_edges(node, data=True):
            if steps == max_steps:
                reasons.add("max_steps")
                return
            steps += 1
            # Only the smallest node starts a cycle, so rotations are not repeated.
            if cycles and neighbor < start:
                continue
            if not visit(neighbor):
                return
            destination = start if cycles else target
            if neighbor == destination:
                if len(found) == max_paths:
                    reasons.add("max_paths")
                    return
                found.append(path + [dict(data)])
            elif neighbor not in ancestors:
                walk(start, neighbor, ancestors | {neighbor}, path + [dict(data)])
            if reasons:
                return

    if not cycles and source == target:
        visit(source)
        found.append([])
    else:
        for start in graph if cycles else (source,):
            if not visit(start):
                break
            walk(start, start, {start}, [])
            if reasons:
                break
    edges = {edge["id"]: edge for path in found for edge in path}
    nodes = {edge[end] for edge in edges.values() for end in ("from", "to")}
    if not cycles:
        nodes.add(source)
    return _result(graph, nodes, list(edges.values()), reasons,
                   **{"cycles" if cycles else "paths": [[edge["id"] for edge in path] for path in found]},
                   source_id=source, target_id=target, search_steps=steps, visited_nodes=len(visited),
                   limits={"max_depth": max_depth, "max_nodes": max_nodes,
                           "max_paths": max_paths, "max_steps": max_steps})


def query_paths(graph, source, target, *, max_depth=3, max_nodes=100, max_paths=10, max_steps=10000):
    return _search_paths(graph, source, target, max_depth=max_depth, max_nodes=max_nodes,
                         max_paths=max_paths, max_steps=max_steps)


def query_cycles(graph, *, max_depth=3, max_nodes=100, max_paths=10, max_steps=10000):
    return _search_paths(graph, None, None, max_depth=max_depth, max_nodes=max_nodes,
                         max_paths=max_paths, max_steps=max_steps)
