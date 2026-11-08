"""CLI and composition root."""
import argparse
import json
import subprocess
import sys
import sqlite3
import platform
from pathlib import Path

from jsonschema import ValidationError

from .application import index_solution
from .evaluation import evaluate, load_benchmark
from .embeddings import SentenceEmbedder
from .language_model import QwenModel
from .answering import answer_source, answer_graph
from .graph_evidence import build_graph_context
from .retrieval import load_source_index, retrieve
from .graph import load_graph, query_dependencies, query_neighborhood, query_paths, query_cycles

PROJECT = Path(__file__).resolve().parents[1] / "extractor/ArchiE.Extractor/ArchiE.Extractor.csproj"
ASSEMBLY = PROJECT.parent / "bin/Debug/net10.0/ArchiE.Extractor.dll"


class RoslynExtractor:
    identity = {"id": "roslyn", "version": "0.1.0", "interface_version": "archie.extractor-interface.v1"}

    def extract(self, request):
        if not ASSEMBLY.is_file():
            raise ValueError(f"Build the extractor first: dotnet build {PROJECT}")
        process = subprocess.run(
            ["dotnet", str(ASSEMBLY)],
            input=json.dumps(request), capture_output=True, text=True,
            timeout=request["options"]["timeout_seconds"],
        )
        if process.returncode:
            raise ValueError(f"Roslyn extractor exited {process.returncode}: {process.stderr.strip()}")
        return json.loads(process.stdout)


def _ask(index, question, embedder, model, chunks, *, mode="source", top_k=5,
         context_budget=4096, max_new_tokens=1024, timeout_seconds=180):
    if mode not in {"source", "graph"}:
        raise ValueError("Answer mode must be source or graph")
    retrieved = retrieve(index, question, embedder, top_k=top_k)
    settings = {"context_budget": context_budget, "max_new_tokens": max_new_tokens, "timeout_seconds": timeout_seconds}
    if mode == "graph":
        context = build_graph_context(load_graph(index), retrieved, chunks)
        return answer_graph(retrieved, question, model, context, **settings)
    return answer_source(retrieved, question, model, **settings)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="archie")
    commands = parser.add_subparsers(dest="command", required=True)
    index = commands.add_parser("index", help="Index a local C# solution or project")
    index.add_argument("path")
    index.add_argument("--output", default="artifacts/index")
    index.add_argument("--embed", action="store_true", help="Generate local source embeddings")
    index.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    retrieval = commands.add_parser("retrieve", help="Find source chunks using local embeddings")
    retrieval.add_argument("index", help="Published index directory")
    retrieval.add_argument("question")
    retrieval.add_argument("--top-k", type=int, default=5)
    retrieval.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    ask = commands.add_parser("ask", help="Answer from source or graph evidence using local Qwen3-4B")
    ask.add_argument("index", help="Published embedding-enabled index directory")
    ask.add_argument("question")
    ask.add_argument("--mode", choices=("source", "graph"), default="source")
    ask.add_argument("--format", choices=("json", "text"), default="json")
    evaluation = commands.add_parser("evaluate", help="Run resumable paired source/graph experiments")
    evaluation.add_argument("benchmark", help="Versioned benchmark JSON file")
    evaluation.add_argument("--index", required=True, help="Matching embedding-enabled index")
    evaluation.add_argument("--output", required=True, help="Run directory; matching existing runs resume")
    evaluation.add_argument("--seed", type=int, default=0)
    evaluation.add_argument("--allow-draft", action="store_true", help="Permit unreviewed development smoke tests")
    evaluation.add_argument("--question-id", action="append", help="Select benchmark question IDs; repeat for a subset")
    for command in (ask, evaluation):
        command.add_argument("--top-k", type=int, default=5)
        command.add_argument("--context-budget", type=int, default=4096)
        command.add_argument("--max-new-tokens", type=int, default=1024)
        command.add_argument("--timeout", type=float, default=180)
        command.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    inspect = commands.add_parser("inspect", help="Query a published index")
    queries = inspect.add_subparsers(dest="query", required=True)
    for name in ("dependencies", "dependents"):
        query = queries.add_parser(name, help="Return source-backed one-hop relationships")
        query.add_argument("index", help="Published index directory")
        query.add_argument("symbol", help="Exact symbol ID from extractor.json")
        query.add_argument("--limit", type=int, default=100, help="Maximum returned edges (1-1000)")
    for name in ("neighborhood", "paths", "cycles"):
        query = queries.add_parser(name, help="Return bounded multi-hop graph evidence")
        query.add_argument("index", help="Published index directory")
        if name != "cycles":
            query.add_argument("symbol", help="Exact source symbol ID")
        if name == "paths":
            query.add_argument("target", help="Exact target symbol ID")
        query.add_argument("--max-depth", type=int, default=2 if name == "neighborhood" else 3)
        query.add_argument("--max-nodes", type=int, default=100)
        if name == "neighborhood":
            query.add_argument("--reverse", action="store_true", help="Follow incoming relationships")
            query.add_argument("--max-edges", type=int, default=1000)
        else:
            query.add_argument("--max-paths", type=int, default=10, help="Maximum returned paths or cycles")
            query.add_argument("--max-steps", type=int, default=10000, help="Maximum examined edges during search")
    args = parser.parse_args(argv)
    try:
        if args.command == "index":
            embedder = (SentenceEmbedder(device=args.device, cache_dir=Path(args.output) / ".models")
                        if args.embed else None)
            destination = index_solution(args.path, args.output, RoslynExtractor(), embedder=embedder)
            print(json.dumps({"status": "complete", "path": str(destination)}))
        elif args.command == "retrieve":
            _, embeddings, _, _ = load_source_index(args.index)
            embedder = SentenceEmbedder(device=args.device, cache_dir=Path(args.index).resolve().parent / ".models",
                                        revision=embeddings["model"]["revision"])
            print(json.dumps(retrieve(args.index, args.question, embedder, top_k=args.top_k)))
        elif args.command == "ask":
            _, embeddings, chunks, _ = load_source_index(args.index)
            embedder = SentenceEmbedder(device=args.device, cache_dir=Path(args.index).resolve().parent / ".models",
                                        revision=embeddings["model"]["revision"])
            model = QwenModel(device=args.device)
            result = _ask(args.index, args.question, embedder, model, chunks, mode=args.mode, top_k=args.top_k,
                          context_budget=args.context_budget, max_new_tokens=args.max_new_tokens, timeout_seconds=args.timeout)
            if args.format == "json" or result["status"] == "failed":
                print(json.dumps(result), file=sys.stderr if result["status"] == "failed" else sys.stdout)
            else:
                print(result["answer"])
                cited = {key for claim in result["claims"] for key in claim["evidence_ids"]}
                for evidence in result["evidence"]:
                    if evidence["id"] in cited:
                        if evidence["kind"] == "source_span":
                            sources = [evidence["source"]]
                        else:
                            path = next(path for path in result["graph_context"]["paths"] if path["evidence_id"] == evidence["id"])
                            sources = [edge["source"] for edge in path["edges"]]
                            labels = [node["qualified_name"] for node in path["nodes"]]
                            print(f"[{evidence['id']}] Graph path: {' -> '.join(labels)}")
                        for source in sources:
                            print(f"[{evidence['id']}] {source['path']}:{source['start_line']}:{source['start_column']}-"
                                  f"{source['end_line']}:{source['end_column']}")
            return 0 if result["status"] == "succeeded" else 1
        elif args.command == "evaluate":
            benchmark = load_benchmark(args.benchmark, allow_draft=args.allow_draft)
            manifest, embeddings, chunks, _ = load_source_index(args.index)
            if manifest["source"]["content_hash"] != benchmark["source"]["content_hash"]:
                raise ValueError("Benchmark source hash does not match the selected index")
            embedder = SentenceEmbedder(device=args.device, cache_dir=Path(args.index).resolve().parent / ".models",
                                        revision=embeddings["model"]["revision"])
            model = QwenModel(device=args.device)
            hardware = platform.machine()
            if model.identity["device"] == "cuda":
                import torch
                hardware = torch.cuda.get_device_name(0)
            configuration = {"model_id": model.identity["model_id"], "model_revision": model.identity["revision"],
                "runtime_version": model.identity["runtime_version"], "device": model.identity["device"],
                "dtype": model.identity["dtype"], "embedding_model_id": embedder.identity["model_id"],
                "embedding_identity": embedder.identity, "context_budget_tokens": args.context_budget,
                "max_new_tokens": args.max_new_tokens, "timeout_seconds": args.timeout, "top_k": args.top_k,
                "hardware": hardware, "python_version": platform.python_version()}
            from .graph_evidence import LIMITS
            configuration["graph_limits"] = dict(LIMITS)
            def answerer(question, mode):
                return _ask(args.index, question, embedder, model, chunks, mode=mode, top_k=args.top_k,
                            context_budget=args.context_budget, max_new_tokens=args.max_new_tokens, timeout_seconds=args.timeout)
            summary = evaluate(benchmark, args.index, args.output, configuration, answerer,
                seed=args.seed, allow_draft=args.allow_draft, question_ids=args.question_id,
                progress=lambda value: print(json.dumps(value), file=sys.stderr, flush=True))
            print(json.dumps({"status": summary["status"], "run_id": summary["run_id"],
                              "path": str(Path(args.output).resolve()), "factual_grading": summary["factual_grading"]}))
            return 1 if any(mode["failed"] or mode["citation_error_records"] for mode in summary["modes"].values()) else 0
        else:
            graph = load_graph(args.index)
            if args.query in {"dependencies", "dependents"}:
                result = query_dependencies(graph, args.symbol,
                                            reverse=args.query == "dependents", limit=args.limit)
            elif args.query == "neighborhood":
                result = query_neighborhood(graph, args.symbol, reverse=args.reverse,
                                            max_depth=args.max_depth, max_nodes=args.max_nodes,
                                            max_edges=args.max_edges)
            else:
                bounds = {"max_depth": args.max_depth, "max_nodes": args.max_nodes,
                          "max_paths": args.max_paths, "max_steps": args.max_steps}
                result = (query_paths(graph, args.symbol, args.target, **bounds) if args.query == "paths"
                          else query_cycles(graph, **bounds))
            print(json.dumps(result))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError, ValidationError, sqlite3.Error) as error:
        print(json.dumps({"status": "failed", "error": str(error)}), file=sys.stderr)
        return 1
