"""Resumable paired experiments; structural citation checks are not factual grading."""
import json
import math
import os
import random
import re
import tempfile
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from time import perf_counter

from jsonschema import ValidationError

from .contracts import validate, validate_generation_limits
from .graph import load_graph
from .graph_evidence import validate_graph_context
from .retrieval import content_hash, load_source_index


def _now():
    return datetime.now(timezone.utc).isoformat()


def _hash(value):
    return content_hash(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False))


def _validate_benchmark(value, allow_draft):
    validate("benchmark", value)
    review = value["review"]
    if review["status"] == "approved":
        if not review["reviewer"] or not review["reviewer"].strip() or not review["reviewed_at"]:
            raise ValueError("Approved benchmarks require a reviewer and review date")
    elif not allow_draft:
        raise ValueError("Benchmark review is pending; use --allow-draft only for development smoke tests")
    ids, facts = set(), set()
    for question in value["questions"]:
        if question["id"] in ids:
            raise ValueError("Duplicate benchmark question ID")
        ids.add(question["id"])
        if not question.get("category") or question.get("expected_action") not in {"answer", "abstain"}:
            raise ValueError("Benchmark questions require category and expected_action")
        if (question["expected_action"] == "answer") != bool(question["expected_facts"]):
            raise ValueError("Answer questions require facts; abstention questions must have none")
        if question["expected_action"] == "answer" and not question.get("acceptable_citations"):
            raise ValueError("Answer questions require acceptable source regions")
        for fact in question["expected_facts"]:
            if fact["id"] in facts:
                raise ValueError("Duplicate benchmark fact ID")
            facts.add(fact["id"])
        for citation in question.get("acceptable_citations", []):
            match = re.fullmatch(r"([^:]+):([1-9][0-9]*)-([1-9][0-9]*)", citation)
            if not match:
                raise ValueError("Benchmark citations must use path:start-end")
            path = PurePosixPath(match[1])
            if path.is_absolute() or ".." in path.parts or "\\" in str(path) or int(match[2]) > int(match[3]):
                raise ValueError("Invalid benchmark citation path or line range")


def load_benchmark(path, *, allow_draft=False):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    _validate_benchmark(value, allow_draft)
    return value


def software_hash():
    root = Path(__file__).resolve().parents[1]
    files = sorted([*root.joinpath("archie").glob("*.py"), *root.joinpath("schemas").glob("*.json"), root / "pyproject.toml"])
    return content_hash("".join(str(path.relative_to(root)) + "\0" + content_hash(path.read_text(encoding="utf-8")) + "\n" for path in files))


def _atomic_json(path, value, *, overwrite=True):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _checkpoint(path, value):
    validate("experiment-record", value)
    _atomic_json(path, value)


def check_citations(answer, graph, chunks):
    """Check cited IDs against canonical index evidence, without judging entailment."""
    validate("answer-record", answer)
    evidence = {item["id"]: item for item in answer["evidence"]}
    cited = {key for claim in answer["claims"] for key in claim.get("evidence_ids", [])}
    errors = []
    ambiguous = {key for key, count in Counter(item["id"] for item in answer["evidence"]).items() if count > 1}
    context_valid = True
    if len(evidence) != len(answer["evidence"]):
        errors.append("Duplicate evidence ID")
    paths = {path["evidence_id"]: path for path in answer.get("graph_context", {}).get("paths", [])}
    if "graph_context" in answer:
        try:
            validate_graph_context(answer["graph_context"])
            if answer["graph_context"]["index_id"] != answer["index_id"]:
                raise ValueError("Graph evidence index identity differs from the answer")
        except (ValueError, ValidationError) as error:
            errors.append(str(error))
            context_valid = False
    valid = 0
    canonical_edges = {edge["id"]: edge for _, _, edge in graph.edges(data=True)}
    for key in sorted(cited):
        item = evidence.get(key)
        ok = item is not None and key not in ambiguous
        if ok and item["kind"] == "source_span":
            ok = any(item["source"] == {name: chunk[name] for name in
                     ("path", "start_line", "start_column", "end_line", "end_column")}
                     and chunk["id"] in answer.get("context_chunk_ids", []) for chunk in chunks.values())
        elif ok and item["kind"] == "graph_path":
            path = paths.get(key)
            ok = (context_valid and path is not None and item["edge_ids"] == [edge["id"] for edge in path["edges"]]
                  and item["node_ids"] == [node["id"] for node in path["nodes"]]
                  and all(edge == canonical_edges.get(edge["id"]) for edge in path["edges"])
                  and all(node["id"] in graph and node == dict(graph.nodes[node["id"]]) for node in path["nodes"])
                  and all(chunk == chunks.get(chunk["id"]) for chunk in path["source_chunks"]))
        elif ok:
            supplied = {edge["id"] for path in answer.get("graph_context", {}).get("paths", []) for edge in path["edges"]}
            ok = context_valid and item.get("edge_id") in canonical_edges and item.get("edge_id") in supplied
        if ok:
            valid += 1
        else:
            errors.append(f"Invalid cited evidence: {key}")
    for claim in answer["claims"]:
        if not claim.get("evidence_ids"):
            errors.append(f"Claim has no citation: {claim['id']}")
    return {"checked": len(cited), "valid": valid, "invalid": len(cited) - valid, "errors": errors}


def _failure(question, mode, manifest, configuration, message, code="EVALUATION_ATTEMPT_FAILED"):
    return {"schema_version": "archie.answer-record.v1", "schema_revision": 2, "question_id": question["id"],
            "question": question["question"], "index_id": manifest["index_id"], "mode": mode, "status": "failed",
            "answer": "", "claims": [], "evidence": [], "run": {
                "model_id": configuration["model_id"], "model_revision": configuration["model_revision"],
                "embedding_model_id": configuration["embedding_model_id"], "runtime_version": configuration["runtime_version"],
                "device": configuration["device"], "dtype": configuration["dtype"], "context_tokens": 0, "latency_ms": 0,
                "context_budget": configuration["context_budget_tokens"], "max_new_tokens": configuration["max_new_tokens"],
                "timeout_seconds": configuration["timeout_seconds"]},
            "error": {"code": code, "severity": "error", "message": message, "component": "evaluation", "recoverable": False}}


def _configuration_matches(answer, configuration):
    expected = {"model_id": "model_id", "model_revision": "model_revision", "runtime_version": "runtime_version",
                "embedding_model_id": "embedding_model_id", "device": "device", "dtype": "dtype",
                "context_budget": "context_budget_tokens", "max_new_tokens": "max_new_tokens", "timeout_seconds": "timeout_seconds"}
    return all(answer["run"].get(key) == configuration[value] for key, value in expected.items())


def _reports(output, state, benchmark, graph, chunks):
    checks = [check_citations(answer, graph, chunks) for answer in state["answers"]]
    modes = {}
    for mode in ("source", "graph"):
        pairs = [(answer, check) for answer, check in zip(state["answers"], checks) if answer["mode"] == mode]
        successful = [answer for answer, _ in pairs if answer["status"] == "succeeded"]
        modes[mode] = {"attempts": len(pairs), "succeeded": len(successful), "failed": len(pairs) - len(successful),
                       "answered": sum(bool(answer["claims"]) for answer in successful),
                       "abstained": sum(not answer["claims"] for answer in successful),
                       "citations_checked": sum(check["checked"] for _, check in pairs),
                       "citations_valid": sum(check["valid"] for _, check in pairs),
                       "citations_invalid": sum(check["invalid"] for _, check in pairs),
                       "citation_error_records": sum(bool(check["errors"]) for _, check in pairs)}
        for field in ("context_tokens", "output_tokens", "latency_ms", "pipeline_latency_ms"):
            values = [answer["run"][field] for answer in successful if field in answer["run"]]
            modes[mode]["mean_" + field] = math.fsum(values) / len(values) if values else None
    summary = {"run_id": state["run_id"], "status": state["status"], "benchmark_version": benchmark["version"],
               "benchmark_review": benchmark["review"]["status"], "factual_grading": "pending_human_review", "modes": modes,
               "citation_checks": [{"question_id": answer["question_id"], "mode": answer["mode"], **check}
                                   for answer, check in zip(state["answers"], checks)]}
    _atomic_json(output / "summary.json", summary)
    review_path = output / "review-template.json"
    if state["status"] == "complete" and not review_path.exists():
        questions = {question["id"]: question for question in benchmark["questions"]}
        items = [{"answer_index": number, "question_id": answer["question_id"], "mode": answer["mode"],
                  "expected_action": questions[answer["question_id"]]["expected_action"],
                  "expected_facts": questions[answer["question_id"]]["expected_facts"],
                  "acceptable_citations": questions[answer["question_id"]].get("acceptable_citations", []),
                  "answer": answer["answer"], "claims": answer["claims"], "status": "pending",
                  "assessment": {"fact_matches": None, "unsupported_claim_ids": None, "correct_abstention": None, "notes": ""}}
                 for number, answer in enumerate(state["answers"])]
        try:
            _atomic_json(review_path, {"run_id": state["run_id"], "status": "pending", "items": items}, overwrite=False)
        except FileExistsError:
            pass  # A review created concurrently must not be replaced.
    return summary


def evaluate(benchmark, index, output, configuration, answerer, *, seed=0, allow_draft=False, question_ids=None, progress=None):
    """Answerer(question_text, mode) returns the same answer record as the ask command."""
    _validate_benchmark(benchmark, allow_draft)
    if type(seed) is not int or seed < 0:
        raise ValueError("Evaluation seed must be a non-negative integer")
    validate_generation_limits(configuration["max_new_tokens"], configuration["timeout_seconds"])
    if type(configuration["top_k"]) is not int or not 1 <= configuration["top_k"] <= 100:
        raise ValueError("Evaluation top_k must be between 1 and 100")
    if type(configuration["context_budget_tokens"]) is not int or not 1 <= configuration["context_budget_tokens"] <= 16384:
        raise ValueError("Evaluation context budget must be between 1 and 16384")
    manifest, embeddings, chunks, _ = load_source_index(index)
    if manifest["source"]["content_hash"] != benchmark["source"]["content_hash"]:
        raise ValueError("Benchmark source hash does not match the selected index")
    if embeddings["model"] != configuration["embedding_identity"]:
        raise ValueError("Embedding model identity does not match the selected index")
    graph = load_graph(index)
    if graph.graph["index_id"] != manifest["index_id"]:
        raise ValueError("Graph and retrieval indexes differ")
    for question in benchmark["questions"]:
        for citation in question.get("acceptable_citations", []):
            path, interval = citation.rsplit(":", 1)
            start, end = map(int, interval.split("-"))
            if not all(any(chunk["path"] == path and chunk["start_line"] <= point <= chunk["end_line"]
                           for chunk in chunks.values()) for point in (start, end)):
                raise ValueError(f"Benchmark source region is not covered by indexed snapshots: {citation}")
    questions = {question["id"]: question for question in benchmark["questions"]}
    selected = list(question_ids) if question_ids is not None else list(questions)
    if not selected or len(set(selected)) != len(selected) or set(selected) - questions.keys():
        raise ValueError("Selected question IDs must be non-empty, unique, and present in the benchmark")
    rng = random.Random(seed)
    order = sorted(selected)
    rng.shuffle(order)
    first_source = rng.choice((True, False))
    schedule = [{"question_id": key, "mode": mode} for number, key in enumerate(order)
                for mode in (("source", "graph") if (number % 2 == 0) == first_source else ("graph", "source"))]
    frozen = {**configuration, "software_hash": software_hash(), "modes": ["source", "graph"]}
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    path = output / "experiment.json"
    fingerprint = {"benchmark_hash": _hash(benchmark), "index_id": manifest["index_id"],
                   "source_content_hash": manifest["source"]["content_hash"], "seed": seed,
                   "configuration": frozen, "execution_order": schedule}
    try:
        from filelock import FileLock
    except ImportError as error:
        raise ValueError('Install evaluation dependencies: python -m pip install -e ".[answering]"') from error
    with FileLock(str(output / ".run.lock"), timeout=0):
        if path.exists():
            state = json.loads(path.read_text(encoding="utf-8"))
            validate("experiment-record", state)
            if any(state.get(key) != value for key, value in fingerprint.items()):
                raise ValueError("Cannot resume: benchmark, index, software, settings, or question selection changed; use a new output directory")
            actual = [{"question_id": answer["question_id"], "mode": answer["mode"]} for answer in state["answers"]]
            if actual != schedule[:len(actual)] or state.get("benchmark_snapshot") != benchmark:
                raise ValueError("Stored evaluation order or benchmark snapshot is invalid")
            for answer in state["answers"]:
                if (answer.get("question") != questions[answer["question_id"]]["question"]
                        or answer.get("index_id") != manifest["index_id"]):
                    raise ValueError("Stored answer question or index identity is invalid")
                if answer["status"] == "succeeded" and not _configuration_matches(answer, frozen):
                    raise ValueError("Stored answer configuration does not match the frozen run")
        else:
            if any(item.name != ".run.lock" for item in output.iterdir()):
                raise ValueError("Output directory is not empty and has no experiment checkpoint")
            state = {"schema_version": "archie.experiment-record.v1", "schema_revision": 2,
                     "run_id": "run:" + uuid.uuid4().hex, "benchmark_version": benchmark["version"],
                     "benchmark_snapshot": benchmark, "answers": [], "status": "running", "started_at": _now(), **fingerprint}
            _checkpoint(path, state)
        if state["status"] == "complete" and len(state["answers"]) != len(schedule):
            raise ValueError("Complete experiment has missing attempts")
        if state.get("in_flight"):
            if len(state["answers"]) >= len(schedule):
                raise ValueError("Interrupted-attempt checkpoint has no pending attempt")
            pending = schedule[len(state["answers"])]
            if state["in_flight"]["question_id"] != pending["question_id"] or state["in_flight"]["mode"] != pending["mode"]:
                raise ValueError("Invalid interrupted-attempt checkpoint")
            state["answers"].append(_failure(questions[pending["question_id"]], pending["mode"], manifest, frozen,
                "Previous attempt was interrupted; no automatic retry was performed", "EVALUATION_INTERRUPTED"))
            del state["in_flight"]
            _checkpoint(path, state)
        for attempt in schedule[len(state["answers"]):]:
            if software_hash() != frozen["software_hash"]:
                raise ValueError("Software changed during evaluation; preserve this run and use a new output directory")
            question, mode = questions[attempt["question_id"]], attempt["mode"]
            state["in_flight"] = {**attempt, "started_at": _now()}
            _checkpoint(path, state)
            started, answer = perf_counter(), None
            try:
                answer = answerer(question["question"], mode)
                validate("answer-record", answer)
                json.dumps(answer, allow_nan=False)
                if answer["question"] != question["question"] or answer["mode"] != mode or answer["index_id"] != manifest["index_id"]:
                    raise ValueError("Answer question, mode, or index differs from the scheduled attempt")
                if not _configuration_matches(answer, frozen) or answer["run"]["context_tokens"] > frozen["context_budget_tokens"]:
                    raise ValueError("Answer metadata differs from the frozen evaluation settings")
            except (ValueError, OSError, ValidationError) as error:
                raw = json.dumps(answer, default=str) if answer is not None else None
                answer = _failure(question, mode, manifest, frozen, str(error))
                if raw is not None:
                    answer["raw_response"] = raw
            answer["question_id"] = question["id"]
            answer["run"]["pipeline_latency_ms"] = (perf_counter() - started) * 1000
            state["answers"].append(answer)
            del state["in_flight"]
            _checkpoint(path, state)
            if progress:
                progress({"question_id": question["id"], "mode": mode, "status": answer["status"],
                          "completed": len(state["answers"]), "total": len(schedule)})
        state["status"], state["finished_at"] = "complete", state.get("finished_at", _now())
        _checkpoint(path, state)
        return _reports(output, state, benchmark, graph, chunks)
