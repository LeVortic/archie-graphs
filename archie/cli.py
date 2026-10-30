"""CLI and composition root."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from jsonschema import ValidationError

from .application import index_solution
from .graph import load_graph, query_dependencies

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
    args = parser.parse_args(argv)
    try:
        if args.command == "index":
            destination = index_solution(args.path, args.output, RoslynExtractor())
            print(json.dumps({"status": "complete", "path": str(destination)}))
        else:
            result = query_dependencies(load_graph(args.index), args.symbol,
                                        reverse=args.query == "dependents", limit=args.limit)
            print(json.dumps(result))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError, ValidationError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}), file=sys.stderr)
        return 1
