"""CLI and composition root."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from .application import index_solution

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
    args = parser.parse_args(argv)
    try:
        destination = index_solution(args.path, args.output, RoslynExtractor())
        print(json.dumps({"status": "complete", "path": str(destination)}))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}), file=sys.stderr)
        return 1
