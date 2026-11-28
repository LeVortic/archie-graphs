# Run ArchiE with Codex or Claude Code

Clone the repository and open a terminal in its root:

```sh
git clone https://github.com/LeVortic/archie-graphs.git
cd archie-graphs
```

Start `codex` or `claude` after installing your coding assistant. See the
[Codex CLI docs](https://developers.openai.com/codex/cli) or
[Claude Code quickstart](https://code.claude.com/docs/en/quickstart).

Paste this prompt into either tool:

> Set up this checkout with Python 3.12, the pinned Python dependencies and
> the .NET SDK selected by global.json. Follow the commands in this guide.
> Build the extractor and the C# fixture, run the tests, then index the
> fixture and show one Controller dependency with its source file and line.
> Report failures with the exact command and error. Keep tracked files
> unchanged.

## Commands the assistant should run

Run these from the repository root with Python 3.12 and .NET 10 on PATH:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python -m pip install --no-deps -e .
dotnet restore extractor/ArchiE.Extractor/ArchiE.Extractor.csproj --locked-mode
dotnet build extractor/ArchiE.Extractor/ArchiE.Extractor.csproj --no-restore
dotnet build fixtures/csharp/Fixture.sln
ARCHIE_REQUIRE_INTEGRATION=1 .venv/bin/python -m pytest -q -rs
.venv/bin/archie index fixtures/csharp/Fixture.sln --output artifacts/index
```

Use the index path printed by the last command:

```sh
.venv/bin/archie inspect dependencies "<index-path>" 'type:App%2FApp.csproj:T%3AFixture.App.Controller'
```

This smoke check uses the bundled fixture and needs no embedding or language
model downloads. See the [README setup](README.md#setup) for SDK troubleshooting.
