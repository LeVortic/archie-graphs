"""Evidence-preserving graphs and bounded one-hop queries."""
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
