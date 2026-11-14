import json
from collections import Counter
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from archie.application import index_solution
from archie.cli import main
from archie.contracts import validate
from archie.evaluation import evaluate, load_benchmark, check_citations
from archie.graph import load_graph
from archie.graph_evidence import LIMITS, build_graph_context
from archie.retrieval import load_source_index

ROOT = Path(__file__).parents[1]


class Embedder:
    device = "cpu"
    max_tokens = 256
    identity = {"model_id": "fake-embedding", "revision": "one", "runtime": "fake", "runtime_version": "1",
                "dimensions": 2, "max_tokens": 256, "normalized": True}
    def count_tokens(self, text): return max(1, len(text) // 4)
    def embed(self, texts): return [[1, 1] for text in texts]


@pytest.fixture
def experiment(tmp_path):
    result = json.loads((ROOT / "fixtures/schemas/valid/extractor-result.json").read_text())
    result["input"]["path"] = str(tmp_path / "App.sln")
    (tmp_path / "App.sln").write_text("fixture")
    for node in result["nodes"]:
        path = tmp_path / node["source"]["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(("// indexed fixture " + " " * 200 + "\n") * 100)
    extractor = SimpleNamespace(identity={key: result["extractor"][key] for key in ("id", "version", "interface_version")},
                                extract=lambda request: deepcopy(result))
    index = index_solution(tmp_path / "App.sln", tmp_path / "indexes", extractor, embedder=Embedder())
    manifest, _, chunks, _ = load_source_index(index)
    graph = load_graph(index)
    chunk = next(chunk for chunk in chunks.values() if chunk["path"].endswith("CheckoutController.cs"))
    configuration = {"model_id": "fake-qwen", "model_revision": "rev", "runtime_version": "test", "device": "cpu",
        "dtype": "float32", "embedding_model_id": Embedder.identity["model_id"], "embedding_identity": Embedder.identity,
        "context_budget_tokens": 2048, "top_k": 5, "max_new_tokens": 128, "timeout_seconds": 20,
        "graph_limits": LIMITS, "hardware": "test", "python_version": "3.12"}
    benchmark = {"schema_version": "archie.benchmark.v1", "version": "test-v1", "split": "development",
        "research_question": "Compare evidence modes", "source": {"id": "fixture", "content_hash": result["input"]["content_hash"],
        "revision": "test", "provenance_note": "test snapshot"},
        "review": {"status": "approved", "reviewer": "Test reviewer", "reviewed_at": "2026-11-08T00:00:00Z"},
        "questions": [{"schema_version": "archie.benchmark-question.v1", "id": "question:dependency", "question": "Which dependency?",
            "expected_facts": [{"id": "fact:one", "text": "Controller depends on Service"}], "dependency_depth": 1,
            "category": "dependency", "expected_action": "answer", "acceptable_citations": [chunk["path"] + ":6-6"]},
            {"schema_version": "archie.benchmark-question.v1", "id": "question:unknown", "question": "Unknown schema?",
             "expected_facts": [], "dependency_depth": 0, "category": "insufficient_evidence", "expected_action": "abstain", "acceptable_citations": []}]}
    calls = []
    context = build_graph_context(graph, {"index_id": manifest["index_id"], "query": "Controller", "matches": [chunk]}, chunks)
    def answerer(question, mode):
        calls.append((question, mode))
        run = {"model_id": configuration["model_id"], "model_revision": configuration["model_revision"],
               "runtime_version": configuration["runtime_version"], "embedding_model_id": configuration["embedding_model_id"],
               "device": "cpu", "dtype": "float32", "context_budget": 2048, "max_new_tokens": 128, "timeout_seconds": 20,
               "context_tokens": 100, "output_tokens": 10, "latency_ms": 5}
        answer = {"schema_version": "archie.answer-record.v1", "question_id": "question:generated", "question": question,
                  "index_id": manifest["index_id"], "mode": mode, "status": "succeeded", "answer": "Insufficient evidence.",
                  "claims": [], "evidence": [], "context_chunk_ids": [], "run": run}
        if question.startswith("Unknown"):
            return answer
        answer["answer"] = "Controller depends on Service."
        answer["claims"] = [{"id": "claim:one", "text": answer["answer"], "support_status": "uncertain", "evidence_ids": ["evidence:1"]}]
        if mode == "source":
            answer["context_chunk_ids"] = [chunk["id"]]
            answer["evidence"] = [{"id": "evidence:1", "kind": "source_span", "source": {key: chunk[key] for key in
                                  ("path", "start_line", "start_column", "end_line", "end_column")}}]
        else:
            path = {**deepcopy(context["paths"][0]), "evidence_id": "evidence:1"}
            answer["graph_context"] = {**deepcopy(context), "paths": [path]}
            answer["context_chunk_ids"] = [chunk["id"] for chunk in path["source_chunks"]]
            answer["evidence"] = [{"id": "evidence:1", "kind": "graph_path", "edge_ids": [edge["id"] for edge in path["edges"]],
                                    "node_ids": [node["id"] for node in path["nodes"]]}]
        return answer
    return SimpleNamespace(index=index, benchmark=benchmark, configuration=configuration, answerer=answerer,
                           calls=calls, graph=graph, chunks=chunks, root=tmp_path)


def run(data, output="run", **kwargs):
    return evaluate(data.benchmark, data.index, data.root / output, data.configuration, data.answerer, seed=42, **kwargs)


def test_counterbalanced_paired_runs_resume_and_preserve_review(experiment):
    summary = run(experiment)
    state = json.loads((experiment.root / "run/experiment.json").read_text())
    validate("experiment-record", state)
    assert len(state["answers"]) == 4 and len(experiment.calls) == 4
    first_modes = Counter(state["execution_order"][n]["mode"] for n in (0, 2))
    assert first_modes == {"source": 1, "graph": 1}
    assert state["benchmark_snapshot"] == experiment.benchmark
    assert summary["factual_grading"] == "pending_human_review"
    assert all(mode["citations_invalid"] == 0 and mode["answered"] == 1 and mode["abstained"] == 1 for mode in summary["modes"].values())
    review = experiment.root / "run/review-template.json"
    review.write_text('{"human_notes":"keep my edits"}')
    assert run(experiment) == summary and len(experiment.calls) == 4
    assert review.read_text() == '{"human_notes":"keep my edits"}'
    run(experiment, output="other")
    other = json.loads((experiment.root / "other/experiment.json").read_text())
    assert state["execution_order"] == other["execution_order"]


def test_draft_gate_and_explicit_smoke_mode(experiment):
    experiment.benchmark["review"] = {"status": "draft", "reviewer": None, "reviewed_at": None}
    with pytest.raises(ValueError, match="pending"):
        run(experiment)
    assert not experiment.calls
    summary = run(experiment, allow_draft=True)
    assert summary["benchmark_review"] == "draft" and summary["factual_grading"] == "pending_human_review"


@pytest.mark.parametrize("change", ["settings", "benchmark", "selection", "software"])
def test_resume_rejects_changed_inputs_without_overwriting(experiment, monkeypatch, change):
    run(experiment)
    path = experiment.root / "run/experiment.json"
    before = path.read_bytes()
    kwargs = {}
    if change == "settings": experiment.configuration["top_k"] = 2
    if change == "benchmark": experiment.benchmark["version"] = "changed"
    if change == "selection": kwargs["question_ids"] = ["question:unknown"]
    if change == "software": monkeypatch.setattr("archie.evaluation.software_hash", lambda: "sha256:" + "0" * 64)
    with pytest.raises(ValueError, match="Cannot resume"):
        run(experiment, **kwargs)
    assert path.read_bytes() == before


def test_failure_is_saved_and_not_automatically_retried(experiment):
    answerer = experiment.answerer
    attempts = []
    def flaky(question, mode):
        attempts.append((question, mode))
        if len(attempts) == 1: raise OSError("runtime unavailable")
        return answerer(question, mode)
    experiment.answerer = flaky
    summary = run(experiment)
    state = json.loads((experiment.root / "run/experiment.json").read_text())
    assert state["answers"][0]["status"] == "failed"
    assert "runtime unavailable" in state["answers"][0]["error"]["message"]
    assert sum(mode["failed"] for mode in summary["modes"].values()) == 1
    run(experiment)
    assert len(attempts) == 4


def test_interruption_is_preserved_and_resume_only_runs_remaining_attempts(experiment):
    answerer = experiment.answerer
    def interrupt(question, mode): raise KeyboardInterrupt()
    experiment.answerer = interrupt
    with pytest.raises(KeyboardInterrupt): run(experiment)
    path = experiment.root / "run/experiment.json"
    interrupted = json.loads(path.read_text())
    assert interrupted["in_flight"] and interrupted["answers"] == []
    experiment.answerer = answerer
    run(experiment)
    state = json.loads(path.read_text())
    assert state["answers"][0]["error"]["code"] == "EVALUATION_INTERRUPTED"
    assert len(state["answers"]) == 4 and len(experiment.calls) == 3
    assert "in_flight" not in state


def test_structural_citations_do_not_grade_fact_correctness(experiment):
    for mode in ("source", "graph"):
        answer = experiment.answerer("Which dependency?", mode)
        answer["claims"][0]["text"] = "A semantically false claim with a real citation."
        checked = check_citations(answer, experiment.graph, experiment.chunks)
        assert checked == {"checked": 1, "valid": 1, "invalid": 0, "errors": []}
        bad = deepcopy(answer)
        bad["claims"][0]["evidence_ids"] = ["evidence:999"]
        assert check_citations(bad, experiment.graph, experiment.chunks)["invalid"] == 1
        if mode == "source": bad["evidence"][0]["source"]["end_column"] += 1
        else: bad["graph_context"]["paths"][0]["edges"][0]["to"] = "type:Wrong"
        bad["claims"][0]["evidence_ids"] = ["evidence:1"]
        assert check_citations(bad, experiment.graph, experiment.chunks)["invalid"] == 1


def test_wrong_answer_configuration_is_saved_as_a_failure(experiment):
    answerer = experiment.answerer
    def wrong(question, mode):
        answer = answerer(question, mode)
        answer["run"]["model_revision"] = "wrong"
        return answer
    experiment.answerer = wrong
    run(experiment)
    state = json.loads((experiment.root / "run/experiment.json").read_text())
    assert all(answer["status"] == "failed" for answer in state["answers"])
    assert all('wrong' in answer["raw_response"] for answer in state["answers"])


@pytest.mark.parametrize("damage", ["source", "citation", "duplicate", "review", "facts"])
def test_invalid_benchmarks_fail_before_inference(experiment, damage):
    if damage == "source": experiment.benchmark["source"]["content_hash"] = "sha256:" + "0" * 64
    if damage == "citation": experiment.benchmark["questions"][0]["acceptable_citations"] = ["../secret.cs:1-9"]
    if damage == "duplicate": experiment.benchmark["questions"][1]["id"] = experiment.benchmark["questions"][0]["id"]
    if damage == "review": experiment.benchmark["review"]["reviewer"] = None
    if damage == "facts": experiment.benchmark["questions"][0]["expected_facts"] = []
    with pytest.raises(ValueError): run(experiment)
    assert not experiment.calls and not (experiment.root / "run/experiment.json").exists()


def test_question_subset_and_unknown_selection(experiment):
    summary = run(experiment, question_ids=["question:unknown"])
    assert len(experiment.calls) == 2
    assert all(mode["attempts"] == 1 for mode in summary["modes"].values())
    with pytest.raises(ValueError): run(experiment, output="bad", question_ids=["question:missing"])


def test_checked_in_benchmarks_are_approved_with_distinct_labels():
    questions = []
    for name, count in (("fixture", 11), ("markovjunior", 18)):
        path = ROOT / f"benchmarks/{name}-v1.json"
        benchmark = load_benchmark(path)
        assert benchmark["review"]["status"] == "approved"
        assert benchmark["review"]["reviewer"].strip() and benchmark["review"]["reviewed_at"]
        assert benchmark["split"] == "development" and len(benchmark["questions"]) == count
        questions += benchmark["questions"]
    assert len({question["id"] for question in questions}) == 29
    assert {0, 1, 2, 3} <= {question["dependency_depth"] for question in questions}


def test_evaluate_cli_and_draft_gate(experiment, monkeypatch, capsys):
    benchmark_path = experiment.root / "benchmark.json"
    experiment.benchmark["review"] = {"status": "draft", "reviewer": None, "reviewed_at": None}
    benchmark_path.write_text(json.dumps(experiment.benchmark))
    identity = {"model_id": "fake-qwen", "revision": "rev", "runtime_version": "test", "device": "cpu", "dtype": "float32"}
    monkeypatch.setattr("archie.cli.SentenceEmbedder", lambda **kwargs: Embedder())
    monkeypatch.setattr("archie.cli.QwenModel", lambda **kwargs: SimpleNamespace(identity=identity))
    monkeypatch.setattr("archie.cli._ask", lambda index, question, *args, mode, **kwargs: experiment.answerer(question, mode))
    arguments = ["evaluate", str(benchmark_path), "--index", str(experiment.index), "--output", str(experiment.root / "cli-run"),
                 "--context-budget", "2048", "--max-new-tokens", "128", "--timeout", "20"]
    assert main(arguments) == 1
    assert "pending" in json.loads(capsys.readouterr().err)["error"]
    assert main(arguments + ["--allow-draft"]) == 0
    assert json.loads(capsys.readouterr().out)["factual_grading"] == "pending_human_review"


def test_concurrent_writer_is_rejected_and_existing_results_are_safe(experiment):
    from filelock import FileLock
    run(experiment)
    output = experiment.root / "run"
    before = (output / "experiment.json").read_bytes()
    with FileLock(str(output / ".run.lock"), timeout=0):
        with pytest.raises(OSError):
            run(experiment)
    assert (output / "experiment.json").read_bytes() == before
    assert len(experiment.calls) == 4


def test_software_change_during_run_stops_before_another_attempt(experiment, monkeypatch):
    values = iter(["sha256:" + "1" * 64, "sha256:" + "2" * 64])
    monkeypatch.setattr("archie.evaluation.software_hash", lambda: next(values))
    with pytest.raises(ValueError, match="changed during"):
        run(experiment)
    state = json.loads((experiment.root / "run/experiment.json").read_text())
    assert state["answers"] == [] and not experiment.calls


def test_checkpoint_write_failure_preserves_previous_results(experiment, monkeypatch):
    run(experiment)
    output = experiment.root / "run"
    before = (output / "experiment.json").read_bytes()
    def fail_replace(*args, **kwargs): raise OSError("disk write failed")
    monkeypatch.setattr("archie.evaluation.os.replace", fail_replace)
    with pytest.raises(OSError, match="disk write failed"):
        run(experiment)
    assert (output / "experiment.json").read_bytes() == before
    assert not list(output.glob("*.tmp"))


def test_nonfinite_model_metadata_is_preserved_as_failed_attempt(experiment):
    answerer = experiment.answerer
    def invalid(question, mode):
        answer = answerer(question, mode)
        answer["run"]["latency_ms"] = float("nan")
        return answer
    experiment.answerer = invalid
    run(experiment)
    state = json.loads((experiment.root / "run/experiment.json").read_text())
    assert all(answer["status"] == "failed" for answer in state["answers"])
    assert all("NaN" in answer["raw_response"] for answer in state["answers"])


def test_resume_rejects_tampered_answer_identity(experiment):
    run(experiment)
    path = experiment.root / "run/experiment.json"
    state = json.loads(path.read_text())
    state["answers"][0]["question"] = "A different question"
    path.write_text(json.dumps(state))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="question or index"):
        run(experiment)
    assert path.read_bytes() == before


def test_held_out_benchmarks_are_frozen_and_distinct_from_development():
    import hashlib
    import re
    frozen = dict(re.findall(r"\| `([\w.-]+\.json)` \|.*\| `([0-9a-f]{64})` \|", (ROOT / "benchmarks/HELDOUT.md").read_text()))
    assert set(frozen) == {"fixture-heldout-v1.json", "markovjunior-heldout-v1.json"}
    development_ids = {question["id"] for name in ("fixture", "markovjunior")
                       for question in load_benchmark(ROOT / f"benchmarks/{name}-v1.json")["questions"]}
    for name, digest in frozen.items():
        path = ROOT / "benchmarks" / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, f"{name} changed after it was frozen"
        benchmark = load_benchmark(path)
        development = load_benchmark(ROOT / f"benchmarks/{name.replace('-heldout', '')}")
        assert benchmark["split"] == "held_out" and benchmark["review"]["status"] == "approved"
        assert benchmark["source"] == development["source"]
        assert not {question["id"] for question in benchmark["questions"]} & development_ids
