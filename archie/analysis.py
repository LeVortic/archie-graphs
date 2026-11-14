"""Paired analysis of a completed, human-graded evaluation run.

Reads experiment.json, a completed review file and the benchmark, and never writes to any of them.
Scores follow benchmarks/PROTOCOL.md: claim precision and fact recall come only from human labels,
abstentions are reported separately from ordinary F1, and failures stay visible.
"""
import hashlib
import json
import math
import re
import statistics
from pathlib import Path

CORRECT_LABELS = {"ok", "extra"}
CLAIM_LABELS = {"ok", "extra", "incorrect", "unsupported"}
MODES = ("source", "graph")


def _digest(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _f1(precision, recall):
    return 0.0 if not precision + recall else 2 * precision * recall / (precision + recall)


def _mean(values):
    values = [value for value in values if value is not None]
    return math.fsum(values) / len(values) if values else None


def _median(values):
    values = [value for value in values if value is not None]
    return statistics.median(values) if values else None


def _validate(experiment, review, benchmark):
    if experiment.get("status") != "complete":
        raise ValueError("The experiment run is not complete")
    if review.get("run_id") != experiment["run_id"]:
        raise ValueError(f"Review is for {review.get('run_id')}, not {experiment['run_id']}")
    if experiment.get("benchmark_version") != benchmark["version"]:
        raise ValueError("Benchmark version does not match the experiment")
    answers = experiment["answers"]
    questions = {question["id"]: question for question in benchmark["questions"]}
    seen = set()
    for item in review["items"]:
        number = item["answer_index"]
        if not 0 <= number < len(answers):
            raise ValueError(f"Review item points to missing answer {number}")
        answer = answers[number]
        if (answer["question_id"], answer["mode"]) != (item["question_id"], item["mode"]):
            raise ValueError(f"Review item {number} does not match its answer record")
        if item.get("status") != "reviewed":
            raise ValueError(f"Answer {number} ({item['question_id']}, {item['mode']}) is not reviewed")
        if answer["question_id"] not in questions:
            raise ValueError(f"Unknown question {answer['question_id']}")
        assessment = item["assessment"]
        claim_ids = {claim["id"] for claim in answer["claims"]}
        labels = assessment.get("claim_labels") or {}
        if set(labels) != claim_ids or not set(labels.values()) <= CLAIM_LABELS:
            raise ValueError(f"Answer {number} has missing or unknown claim labels")
        fact_ids = {fact["id"] for fact in questions[answer["question_id"]]["expected_facts"]}
        if set(assessment.get("fact_matches") or {}) != fact_ids:
            raise ValueError(f"Answer {number} does not mark every expected fact")
        seen.add(number)
    if seen != set(range(len(answers))):
        raise ValueError(f"Review covers {len(seen)} of {len(answers)} answers")


def _score(answer, item, question):
    record = {"question_id": answer["question_id"], "mode": answer["mode"], "status": answer["status"],
              "expected_action": question["expected_action"], "dependency_depth": question.get("dependency_depth"),
              "category": question.get("category")}
    run = answer.get("run") or {}
    for field in ("context_tokens", "output_tokens", "latency_ms", "pipeline_latency_ms"):
        record[field] = run.get(field)
    if answer["status"] != "succeeded":
        record["outcome"] = "failed"
        return record
    assessment = item["assessment"]
    labels = assessment["claim_labels"]
    record["claims"] = len(labels)
    for label in CLAIM_LABELS:
        record[label] = sum(value == label for value in labels.values())
    abstained = not answer["claims"]
    if question["expected_action"] == "abstain":
        record["outcome"] = "correct_abstention" if abstained and assessment.get("correct_abstention") else (
            "incorrect_abstention" if abstained else "answered_unanswerable")
        return record
    facts = assessment["fact_matches"]
    record["facts_expected"] = len(facts)
    record["facts_recovered"] = sum(bool(value) for value in facts.values())
    record["recall"] = record["facts_recovered"] / len(facts)
    if abstained:
        record["outcome"] = "abstained_answerable"
        record["precision"] = None
        record["f1"] = None
        record["f1_abstain_as_zero"] = 0.0
    else:
        record["outcome"] = "answered"
        record["precision"] = sum(value in CORRECT_LABELS for value in labels.values()) / len(labels)
        record["f1"] = _f1(record["precision"], record["recall"])
        record["f1_abstain_as_zero"] = record["f1"]
    return record


def _mode_summary(records):
    answerable = [r for r in records if r["expected_action"] == "answer" and r["outcome"] != "failed"]
    answered = [r for r in answerable if r["outcome"] == "answered"]
    unanswerable = [r for r in records if r["expected_action"] == "abstain" and r["outcome"] != "failed"]
    return {
        "attempts": len(records),
        "failed": sum(r["outcome"] == "failed" for r in records),
        "answerable_questions": len(answerable),
        "answered": len(answered),
        "abstained_on_answerable": len(answerable) - len(answered),
        "macro_precision_answered": _mean([r["precision"] for r in answered]),
        "macro_recall_answered": _mean([r["recall"] for r in answered]),
        "macro_f1_answered": _mean([r["f1"] for r in answered]),
        "macro_recall_all_answerable": _mean([r["recall"] for r in answerable]),
        "macro_f1_abstain_as_zero": _mean([r["f1_abstain_as_zero"] for r in answerable]),
        "unanswerable_questions": len(unanswerable),
        "correct_abstentions": sum(r["outcome"] == "correct_abstention" for r in unanswerable),
        "claims": sum(r.get("claims", 0) for r in records),
        **{f"claims_{label}": sum(r.get(label, 0) for r in records) for label in sorted(CLAIM_LABELS)},
        **{f"mean_{field}": _mean([r[field] for r in records]) for field in
           ("context_tokens", "output_tokens", "latency_ms", "pipeline_latency_ms")},
        **{f"median_{field}": _median([r[field] for r in records]) for field in ("context_tokens", "latency_ms")},
    }


def _paired(records):
    by_question = {}
    for record in records:
        if record["expected_action"] == "answer" and record["outcome"] != "failed":
            by_question.setdefault(record["question_id"], {})[record["mode"]] = record
    pairs = [modes for modes in by_question.values() if set(modes) == set(MODES)]
    result = {}
    for key, metric in (("abstain_as_zero", "f1_abstain_as_zero"), ("both_answered", "f1")):
        usable = [modes for modes in pairs if modes["source"][metric] is not None and modes["graph"][metric] is not None]
        differences = [modes["graph"][metric] - modes["source"][metric] for modes in usable]
        result[key] = {"pairs": len(usable), "mean_graph_minus_source": _mean(differences),
                       "graph_better": sum(d > 1e-9 for d in differences),
                       "source_better": sum(d < -1e-9 for d in differences),
                       "ties": sum(abs(d) <= 1e-9 for d in differences)}
    return result


def _group(records):
    return {"modes": {mode: _mode_summary([r for r in records if r["mode"] == mode]) for mode in MODES},
            "paired_f1": _paired(records)}


def analyze(experiment_path, review_path, benchmark_path, subsets=None):
    """Return the analysis as a dict; subsets maps a name to a regular expression over question IDs."""
    experiment = json.loads(Path(experiment_path).read_text(encoding="utf-8"))
    review = json.loads(Path(review_path).read_text(encoding="utf-8"))
    benchmark = json.loads(Path(benchmark_path).read_text(encoding="utf-8"))
    _validate(experiment, review, benchmark)
    questions = {question["id"]: question for question in benchmark["questions"]}
    items = {item["answer_index"]: item for item in review["items"]}
    records = [_score(answer, items[number], questions[answer["question_id"]])
               for number, answer in enumerate(experiment["answers"])]
    groups = {"all": records, "multi_hop (depth >= 2)": [r for r in records if (r["dependency_depth"] or 0) >= 2]}
    for depth in sorted({r["dependency_depth"] for r in records if r["dependency_depth"] is not None}):
        groups[f"depth {depth}"] = [r for r in records if r["dependency_depth"] == depth]
    for name, pattern in (subsets or {}).items():
        expression = re.compile(pattern)
        groups[name] = [r for r in records if expression.search(r["question_id"])]
    return {
        "schema_version": "archie.analysis.v1",
        "run_id": experiment["run_id"],
        "benchmark_version": benchmark["version"],
        "model_id": experiment["configuration"].get("model_id"),
        "reviewer": review.get("reviewer"),
        "reviewed_at": review.get("reviewed_at"),
        "inputs": {name: {"path": str(path), "sha256": _digest(path)} for name, path in
                   (("experiment", experiment_path), ("review", review_path), ("benchmark", benchmark_path))},
        "definitions": {
            "precision": "correct claims (ok + extra) / all claims in an answer; whole claims as produced by the model",
            "recall": "expected facts marked recovered / expected facts",
            "macro_*_answered": "mean over answerable questions the mode answered (abstentions excluded)",
            "macro_f1_abstain_as_zero": "mean over all answerable questions, an abstention scoring F1 = 0",
            "paired_f1": "per-question graph minus source F1 on questions with a scored answer in both modes",
        },
        "groups": {name: _group(group) for name, group in groups.items()},
        "per_answer": records,
    }


def analyze_to_file(experiment_path, review_path, benchmark_path, output_path, subsets=None):
    output_path = Path(output_path).resolve()
    if output_path in {Path(p).resolve() for p in (experiment_path, review_path, benchmark_path)}:
        raise ValueError("The analysis output must not replace an input record")
    result = analyze(experiment_path, review_path, benchmark_path, subsets)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result
