"""CLI and composition root."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from jsonschema import ValidationError

from .application import index_solution
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


def main(argv=None):
    parser = argparse.ArgumentParser(prog="archie")
    commands = parser.add_subparsers(dest="command", required=True)
    index = commands.add_parser("index", help="Index a local C# solution or project")
    index.add_argument("path")
    index.add_argument("--output", default="artifacts/index")
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
            destination = index_solution(args.path, args.output, RoslynExtractor())
            print(json.dumps({"status": "complete", "path": str(destination)}))
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
    except (ValueError, OSError, subprocess.SubprocessError, ValidationError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}), file=sys.stderr)
        return 1
