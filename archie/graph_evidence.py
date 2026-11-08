"""Bounded, snapshot-backed graph paths anchored to retrieved source."""
import re
from collections import defaultdict, deque

from .contracts import validate
from .graph import query_neighborhood, query_paths

LIMITS = {"max_seeds": 5, "max_depth": 2, "max_nodes_per_seed": 100,
          "max_edges_per_seed": 30, "max_paths": 20, "max_paths_per_pair": 2, "max_steps_per_pair": 1000}


def _bounds(source):
    return ((source["start_line"], source["start_column"]), (source["end_line"], source["end_column"]))


def _overlaps(left, right):
    return left["path"] == right["path"] and _bounds(left)[0] <= _bounds(right)[1] and _bounds(right)[0] <= _bounds(left)[1]


def _backed(span, chunks):
    return all(any(chunk["path"] == span["path"] and _bounds(chunk)[0] <= point <= _bounds(chunk)[1]
                   for chunk in chunks) for point in _bounds(span))


def clipped_excerpt(span, chunk):
    """Clip a validated snapshot to the edge overlap using UTF-16 columns."""
    start, end = max(_bounds(span)[0], _bounds(chunk)[0]), min(_bounds(span)[1], _bounds(chunk)[1])
    lines = chunk["text"].split("\n")
    first, last = start[0] - chunk["start_line"], end[0] - chunk["start_line"]
    low = start[1] - (chunk["start_column"] if first == 0 else 1)
    high = end[1] - (chunk["start_column"] if last == 0 else 1) + 1
    if first == last:
        text = lines[first].encode("utf-16-le")[low * 2:high * 2].decode("utf-16-le")
    else:
        text = "\n".join([lines[first].encode("utf-16-le")[low * 2:].decode("utf-16-le"),
                          *lines[first + 1:last], lines[last].encode("utf-16-le")[:high * 2].decode("utf-16-le")])
    return {"path": span["path"], "start_line": start[0], "start_column": start[1],
            "end_line": end[0], "end_column": end[1], "text": text}


def validate_graph_context(context):
    validate("graph-context", context)
    seen = set()
    for path in context["paths"]:
        nodes, edges = path["nodes"], path["edges"]
        key = tuple(edge["id"] for edge in edges)
        if key in seen or len(nodes) != len(edges) + 1:
            raise ValueError("Duplicate or disconnected graph evidence path")
        seen.add(key)
        for number, edge in enumerate(edges):
            if (edge["from"] != nodes[number]["id"] or edge["to"] != nodes[number + 1]["id"]
                    or edge["status"] != "extracted" or not _backed(edge["source"], path["source_chunks"])):
                raise ValueError("Graph evidence must be connected, extracted, and snapshot-backed")


def build_graph_context(graph, retrieved, chunks):
    if graph.graph["index_id"] != retrieved["index_id"]:
        raise ValueError("Graph and retrieval must use the same index")
    query = retrieved.get("query", "")
    words = {word.casefold() for word in re.findall(r"\w+", query)}
    references = {word.casefold() for word in re.findall(r"\b\w+(?:\.\w+)+\b", query)}
    named, ranks = set(), {}
    for rank, chunk in enumerate(retrieved["matches"]):
        for key, node in graph.nodes(data=True):
            if "source" in node and _overlaps(node["source"], chunk):
                label = node["qualified_name"].split("(")[0].casefold()
                explicit = any(label == reference or label.endswith("." + reference) for reference in references)
                if explicit:
                    named.add(key)
                priority = (not explicit, node["name"].casefold() not in words, rank, node["kind"] != "type",
                            node["source"]["end_line"] - node["source"]["start_line"], key)
                ranks[key] = min(ranks.get(key, priority), priority)
    candidates = sorted(ranks, key=ranks.get)
    seeds = candidates[:LIMITS["max_seeds"]]
    reasons = {"max_seeds"} if len(candidates) > len(seeds) else set()
    by_file = defaultdict(list)
    for chunk in chunks.values():
        by_file[chunk["path"]].append(chunk)
    for values in by_file.values():
        values.sort(key=lambda chunk: (*_bounds(chunk)[0], chunk["id"]))
    paths, seen_paths, skipped, edge_chunks = [], set(), set(), {}

    def make_path(edges):
        for edge in edges:
            if edge["id"] not in edge_chunks:
                edge_chunks[edge["id"]] = [chunk for chunk in by_file[edge["source"]["path"]]
                                            if _overlaps(edge["source"], chunk)]
            if not _backed(edge["source"], edge_chunks[edge["id"]]):
                skipped.add(edge["id"])
                return None
        node_ids = [edges[0]["from"]] + [edge["to"] for edge in edges]
        sources = {chunk["id"]: chunk for edge in edges for chunk in edge_chunks[edge["id"]]}
        return {"nodes": [dict(graph.nodes[key]) for key in node_ids], "edges": edges,
                "source_chunks": sorted(sources.values(), key=lambda chunk: chunk["id"])}

    def preferred_paths():
        anchors = [seed for seed in seeds if seed in named]
        for source in anchors:
            for target in anchors:
                if source == target:
                    continue
                result = query_paths(graph, source, target, max_depth=LIMITS["max_depth"],
                    max_nodes=LIMITS["max_nodes_per_seed"], max_paths=LIMITS["max_paths_per_pair"],
                    max_steps=LIMITS["max_steps_per_pair"])
                reasons.update("path_" + reason for reason in result["truncation_reasons"])
                edges = {edge["id"]: edge for edge in result["edges"]}
                for edge_ids in result["paths"]:
                    path = make_path([edges[key] for key in edge_ids])
                    if path:
                        yield path

    def nearby_paths(seed):
        neighborhood = query_neighborhood(graph, seed, max_depth=LIMITS["max_depth"],
            max_nodes=LIMITS["max_nodes_per_seed"], max_edges=LIMITS["max_edges_per_seed"])
        reasons.update(reason + "_per_seed" for reason in neighborhood["truncation_reasons"])
        outgoing = defaultdict(list)
        for edge in neighborhood["edges"]:
            outgoing[edge["from"]].append(edge)
        pending = deque([([seed], [])])
        while pending:
            node_ids, prefix = pending.popleft()
            for edge in outgoing[node_ids[-1]]:
                edges = prefix + [edge]
                path = make_path(edges)
                if path is None:
                    continue
                yield path
                if len(edges) < LIMITS["max_depth"] and edge["to"] not in node_ids:
                    pending.append((node_ids + [edge["to"]], edges))

    def candidates_in_order():
        yield from preferred_paths()
        # Share the remaining slots across seeds so one high-degree node cannot consume every slot.
        active = deque(iter(nearby_paths(seed)) for seed in seeds)
        while active:
            stream = active.popleft()
            path = next(stream, None)
            if path is not None:
                yield path
                active.append(stream)

    for path in candidates_in_order():
        key = tuple(edge["id"] for edge in path["edges"])
        if key in seen_paths:
            continue
        if len(paths) == LIMITS["max_paths"]:
            reasons.add("max_paths")
            break
        seen_paths.add(key)
        paths.append(path)
    context = {"index_id": retrieved["index_id"], "extractor": graph.graph["extractor"], "paths": paths,
               "diagnostics": {"seed_node_ids": seeds, "limits": dict(LIMITS),
                               "truncated": bool(reasons), "truncation_reasons": sorted(reasons),
                               "skipped_unbacked_edges": len(skipped)}}
    validate_graph_context(context)
    return context
