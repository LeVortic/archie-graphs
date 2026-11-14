# Held-out benchmark questions (frozen)

These files are the frozen held-out set. They have not been run against any model or retrieval setting.

| File | Version | Questions | SHA-256 |
| --- | --- | ---: | --- |
| `fixture-heldout-v1.json` | `fixture-heldout-v1` | 1 | `69560d38b55c56cdb2e8f8c138da01609ae3da850fed36d2d4f0c717087743eb` |
| `markovjunior-heldout-v1.json` | `markovjunior-heldout-v1` | 3 | `550f773b16ca647a6c49ea0d49a95a1c15816f18ec806891541b2df0ec9650b0` |

Frozen on 14 November 2026 by Rosa Cortes. The questions were drafted with Claude and checked by hand against the source and the extracted graph. Three are multi-hop paths (depth 2, 3 and 2) and one is a reverse dependency (depth 1). Each file uses the same source snapshot hash as its development benchmark.

## Rules

- **Do not run these questions** during development, prompt or retrieval tuning, or smoke tests. Run them only in a formal evaluation, after its settings are fixed and recorded.
- **Do not edit a frozen file.** `tests/test_evaluation.py` checks the hashes above, so an edit fails the test suite. To change a question, publish a new version (for example `-heldout-v2`) and freeze it in this table.
- **Record every run.** Note each formal run against a held-out file here, with its run ID and date. A held-out file that has been run is no longer unseen for later experiments.
- **Second review.** A second reviewer, such as Victor, should review the questions before the formal run. Record that review as a new version, because changing the `review` block changes the hash.

## Runs

None yet.
