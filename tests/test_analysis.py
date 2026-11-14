import copy
import json

import pytest

from archie.analysis import analyze, analyze_to_file
from archie.cli import main

BENCHMARK = {"version": "toy-v1", "questions": [
    {"id": "question:a", "expected_action": "answer", "dependency_depth": 2, "category": "path",
     "expected_facts": [{"id": "fact:a-1", "text": "one"}, {"id": "fact:a-2", "text": "two"}]},
    {"id": "question:b", "expected_action": "answer", "dependency_depth": 1, "category": "dependency",
     "expected_facts": [{"id": "fact:b-1", "text": "one"}]},
    {"id": "question:none", "expected_action": "abstain", "dependency_depth": 0, "category": "insufficient_evidence",
     "expected_facts": []},
]}


def _answer(question, mode, claims, context=100, status="succeeded"):
    return {"question_id": question, "mode": mode, "status": status, "answer": "",
            "claims": [{"id": f"claim:{n}", "text": "x", "evidence_ids": []} for n in range(1, claims + 1)],
            "run": {"context_tokens": context, "output_tokens": 10, "latency_ms": 1000.0, "pipeline_latency_ms": 1500.0}}


def _item(number, answer, labels, facts, abstention=None):
    return {"answer_index": number, "question_id": answer["question_id"], "mode": answer["mode"], "status": "reviewed",
            "assessment": {"claim_labels": labels, "fact_matches": facts, "correct_abstention": abstention, "notes": ""}}


@pytest.fixture
def records(tmp_path):
    answers = [
        _answer("question:a", "source", 0, 100),  # abstains on an answerable question
        _answer("question:a", "graph", 2, 300),
        _answer("question:b", "source", 2, 100),
        _answer("question:b", "graph", 1, 300),
        _answer("question:none", "source", 0, 100),
        _answer("question:none", "graph", 0, 300),
    ]
    items = [
        _item(0, answers[0], {}, {"fact:a-1": False, "fact:a-2": False}),
        _item(1, answers[1], {"claim:1": "ok", "claim:2": "unsupported"}, {"fact:a-1": True, "fact:a-2": False}),
        _item(2, answers[2], {"claim:1": "ok", "claim:2": "extra"}, {"fact:b-1": True}),
        _item(3, answers[3], {"claim:1": "incorrect"}, {"fact:b-1": False}),
        _item(4, answers[4], {}, {}, True),
        _item(5, answers[5], {}, {}, True),
    ]
    experiment = {"status": "complete", "run_id": "run:toy", "benchmark_version": "toy-v1",
                  "configuration": {"model_id": "model"}, "answers": answers}
    review = {"run_id": "run:toy", "reviewer": "Reviewer", "items": items}
    paths = {}
    for name, value in (("experiment", experiment), ("review", review), ("benchmark", BENCHMARK)):
        paths[name] = tmp_path / f"{name}.json"
        paths[name].write_text(json.dumps(value))
    return paths


def test_scores_follow_human_labels_and_keep_abstentions_separate(records):
    result = analyze(records["experiment"], records["review"], records["benchmark"])
    source, graph = (result["groups"]["all"]["modes"][mode] for mode in ("source", "graph"))
    assert source["answered"] == 1 and source["abstained_on_answerable"] == 1
    assert source["macro_f1_answered"] == 1.0 and source["macro_f1_abstain_as_zero"] == 0.5
    assert graph["macro_precision_answered"] == 0.25 and graph["macro_recall_answered"] == 0.25
    assert graph["macro_f1_answered"] == pytest.approx((2 * 0.5 * 0.5) / 1.0 / 2)
    assert source["correct_abstentions"] == graph["correct_abstentions"] == 1
    assert graph["claims_incorrect"] == graph["claims_unsupported"] == 1
    assert graph["mean_context_tokens"] == 300 and source["failed"] == 0
    paired = result["groups"]["all"]["paired_f1"]
    assert paired["abstain_as_zero"]["pairs"] == 2 and paired["both_answered"]["pairs"] == 1
    assert paired["abstain_as_zero"]["graph_better"] == 1 and paired["abstain_as_zero"]["source_better"] == 1
    multi_hop = result["groups"]["multi_hop (depth >= 2)"]["modes"]["graph"]
    assert multi_hop["answerable_questions"] == 1


def test_inputs_are_never_modified_and_hashes_are_recorded(records, tmp_path):
    before = {name: path.read_bytes() for name, path in records.items()}
    result = analyze_to_file(records["experiment"], records["review"], records["benchmark"], tmp_path / "analysis.json",
                             subsets={"only b": "question:b$"})
    assert {name: path.read_bytes() for name, path in records.items()} == before
    assert result["inputs"]["review"]["sha256"].startswith("sha256:")
    assert result["groups"]["only b"]["modes"]["source"]["answerable_questions"] == 1
    with pytest.raises(ValueError, match="must not replace"):
        analyze_to_file(records["experiment"], records["review"], records["benchmark"], records["review"])


@pytest.mark.parametrize("damage", ["pending", "missing_label", "wrong_run", "missing_item"])
def test_incomplete_or_mismatched_reviews_are_rejected(records, damage):
    review = json.loads(records["review"].read_text())
    if damage == "pending":
        review["items"][1]["status"] = "pending"
    elif damage == "missing_label":
        review["items"][1]["assessment"]["claim_labels"].pop("claim:2")
    elif damage == "wrong_run":
        review["run_id"] = "run:other"
    else:
        review["items"].pop()
    records["review"].write_text(json.dumps(review))
    with pytest.raises(ValueError):
        analyze(records["experiment"], records["review"], records["benchmark"])


def test_failures_stay_visible(records):
    experiment = json.loads(records["experiment"].read_text())
    failed = copy.deepcopy(experiment)
    failed["answers"][3] = _answer("question:b", "graph", 0, status="failed")
    records["experiment"].write_text(json.dumps(failed))
    review = json.loads(records["review"].read_text())
    review["items"][3]["assessment"].update(claim_labels={}, fact_matches={"fact:b-1": False})
    records["review"].write_text(json.dumps(review))
    graph = analyze(records["experiment"], records["review"], records["benchmark"])["groups"]["all"]["modes"]["graph"]
    assert graph["failed"] == 1 and graph["answerable_questions"] == 1


def test_analyze_cli(records, tmp_path, capsys):
    run = tmp_path / "run"
    run.mkdir()
    (run / "experiment.json").write_bytes(records["experiment"].read_bytes())
    output = tmp_path / "out.json"
    assert main(["analyze", str(run), "--review", str(records["review"]), "--benchmark", str(records["benchmark"]),
                 "--output", str(output), "--subset", "a=question:a"]) == 0
    assert json.loads(capsys.readouterr().out)["run_id"] == "run:toy"
    assert "a" in json.loads(output.read_text())["groups"]
    assert main(["analyze", str(run), "--review", str(records["review"]), "--benchmark", str(records["benchmark"]),
                 "--output", str(output), "--subset", "no-equals-sign"]) == 1
