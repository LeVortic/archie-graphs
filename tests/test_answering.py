import json
import subprocess
import sys
from copy import deepcopy
from types import SimpleNamespace

import pytest

from archie.answering import answer_source
from archie.cli import main
from archie.contracts import validate
from archie.language_model import QwenModel


@pytest.fixture
def retrieved():
    return {"index_id": "index:fixture", "model": {"model_id": "fake-embedding"},
            "extraction_status": "succeeded", "source_diagnostics": [],
            "matches": [{"id": "chunk:" + str(n) * 64, "path": f"src/{n}.cs", "start_line": 1,
                         "start_column": 1, "end_line": 1, "end_column": 10, "text": "class App {}"}
                        for n in (1, 2)]}


class FakeModel:
    identity = {"model_id": "qwen-test", "revision": "a" * 40, "device": "cpu",
                "dtype": "float32", "runtime_version": "fake:1"}

    def __init__(self):
        self.calls = []
        self.value = {"abstain": False, "claims": [{"text": "App is a class.", "evidence_ids": ["evidence:1"]}]}
        self.finish_reason = "stop"

    def count_tokens(self, messages):
        return (len(json.dumps(messages)) + 3) // 4

    def complete(self, messages, **settings):
        self.calls.append((messages, settings))
        return {"text": json.dumps(self.value), "input_tokens": self.count_tokens(messages),
                "output_tokens": 50, "latency_ms": 10, "finish_reason": self.finish_reason}


def test_source_answer_contract_and_unverified_support(retrieved):
    model = FakeModel()
    result = answer_source(retrieved, "What is App?", model)
    validate("answer-record", result)
    assert result["status"] == "succeeded"
    assert result["mode"] == "source" and result["index_id"] == "index:fixture"
    assert result["claims"][0]["support_status"] == "uncertain"
    assert result["claims"][0]["evidence_ids"] == ["evidence:1"]
    assert result["evidence"][0]["source"]["path"] == "src/1.cs"
    assert result["run"]["context_tokens"] <= 4096
    assert result["run"]["model_revision"] == "a" * 40
    assert model.calls[0][1]["max_new_tokens"] == 1024 and model.calls[0][1]["timeout_seconds"] == 180
    enum = model.calls[0][1]["response_schema"]["properties"]["claims"]["items"]["properties"]["evidence_ids"]["items"]["enum"]
    assert enum == ["evidence:1", "evidence:2"]
    assert result == answer_source(retrieved, "What is App?", model)


def test_context_budget_selection_and_abstention_without_generation(retrieved):
    model = FakeModel()
    full = answer_source(retrieved, "What is App?", model)
    one = deepcopy(retrieved)
    one["matches"].pop()
    budget = answer_source(one, "What is App?", model)["run"]["context_tokens"]
    result = answer_source(retrieved, "What is App?", model, context_budget=budget)
    assert result["run"]["truncated"] and len(result["context_chunk_ids"]) == 1
    assert full["run"]["context_tokens"] > budget
    model.calls.clear()
    retrieved["matches"] = []
    result = answer_source(retrieved, "What is App?", model)
    assert result["status"] == "succeeded" and result["claims"] == [] and not model.calls
    assert "Insufficient evidence" in result["answer"]
    result = answer_source(retrieved, "What is App?", model, context_budget=1)
    assert result["status"] == "failed" and not model.calls


@pytest.mark.parametrize("damage", ["unknown_citation", "no_citation", "unknown_field", "abstain_claims", "empty_claims", "length", "malformed", "timeout", "tokens"])
def test_bad_model_responses_preserve_failure_and_never_publish_claims(retrieved, damage):
    model = FakeModel()
    if damage == "unknown_citation":
        model.value["claims"][0]["evidence_ids"] = ["evidence:99"]
    elif damage == "no_citation":
        model.value["claims"][0]["evidence_ids"] = []
    elif damage == "unknown_field":
        model.value["extra"] = True
    elif damage == "abstain_claims":
        model.value["abstain"] = True
    elif damage == "empty_claims":
        model.value["claims"] = []
    elif damage == "length":
        model.finish_reason = "length"
    elif damage == "timeout":
        def fail(*args, **kwargs):
            raise ValueError("Local generation exceeded deadline")
        model.complete = fail
    else:
        complete = model.complete
        def damaged(messages, **kwargs):
            result = complete(messages, **kwargs)
            result.update({"text": "{broken"} if damage == "malformed" else {"input_tokens": 0})
            return result
        model.complete = damaged
    result = answer_source(retrieved, "What is App?", model)
    validate("answer-record", result)
    assert result["status"] == "failed" and result["claims"] == [] and result["answer"] == ""
    assert result["error"]["code"] == "ANSWER_FAILED"


def test_model_abstention_and_partial_extraction_metadata(retrieved):
    model = FakeModel()
    model.value = {"abstain": True, "claims": []}
    retrieved["extraction_status"] = "partial"
    retrieved["source_diagnostics"] = [{"code": "WARNING", "severity": "warning", "message": "partial",
                                        "component": "fake", "recoverable": True}]
    result = answer_source(retrieved, "What is App?", model)
    assert result["status"] == "succeeded" and result["claims"] == []
    assert result["extraction_status"] == "partial" and result["source_diagnostics"]


@pytest.mark.parametrize("settings", [{"context_budget": 0}, {"context_budget": True}, {"context_budget": 16385},
                                      {"max_new_tokens": 0}, {"max_new_tokens": 4097}, {"max_new_tokens": True},
                                      {"timeout_seconds": 0}, {"timeout_seconds": float("nan")}, {"timeout_seconds": 3601}])
def test_answer_settings_are_bounded(retrieved, settings):
    with pytest.raises(ValueError):
        answer_source(retrieved, "question", FakeModel(), **settings)


@pytest.fixture
def adapter(monkeypatch, tmp_path):
    tokenizer = SimpleNamespace(model_max_length=100000,
        apply_chat_template=lambda messages, **kwargs: json.dumps(messages),
        __call__=None)

    class Tokenizer:
        model_max_length = 100000
        apply_chat_template = staticmethod(tokenizer.apply_chat_template)
        def __call__(self, text, **kwargs):
            return {"input_ids": list(range(len(text)))}

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True)))
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(
        hf_hub_download=lambda *args, **kwargs: "/cache/snapshots/" + "a" * 40 + "/config.json"))
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(AutoTokenizer=SimpleNamespace(
        from_pretrained=lambda *args, **kwargs: Tokenizer())))
    monkeypatch.setattr("archie.language_model.version", lambda name: "test")
    return QwenModel(device="auto", cache_dir=tmp_path)


def test_qwen_subprocess_contract_and_deadline(adapter, monkeypatch):
    messages = [{"role": "user", "content": "hello"}]
    captured = {}
    def run(command, **kwargs):
        captured.update(kwargs)
        request = json.loads(kwargs["input"])
        return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps({"text": "hello", "input_tokens": len(request["prompt"]),
                               "output_tokens": 3, "finish_reason": "stop"}))
    monkeypatch.setattr("archie.language_model.subprocess.run", run)
    result = adapter.complete(messages, max_new_tokens=10, timeout_seconds=2)
    assert result["text"] == "hello" and captured["timeout"] == 2
    assert adapter.identity["device"] == "cuda" and adapter.identity["dtype"] == "bfloat16"
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("worker", 2)
    monkeypatch.setattr("archie.language_model.subprocess.run", timeout)
    with pytest.raises(ValueError, match="exceeded"):
        adapter.complete(messages, timeout_seconds=2)


@pytest.mark.parametrize("damage", ["returncode", "json", "tokens", "count", "reason"])
def test_qwen_rejects_failed_or_invalid_worker_responses(adapter, monkeypatch, damage):
    messages = [{"role": "user", "content": "hello"}]
    result = {"text": "hi", "input_tokens": adapter.count_tokens(messages), "output_tokens": 2, "finish_reason": "stop"}
    if damage == "tokens": result["input_tokens"] = 0
    if damage == "count": result["output_tokens"] = 99999
    if damage == "reason": result["finish_reason"] = "unknown"
    monkeypatch.setattr("archie.language_model.subprocess.run", lambda *args, **kwargs: SimpleNamespace(
        returncode=1 if damage == "returncode" else 0, stderr="worker failed", stdout="{bad" if damage == "json" else json.dumps(result)))
    with pytest.raises(ValueError):
        adapter.complete(messages)
    with pytest.raises(ValueError, match="context limit"):
        adapter.complete([{"role": "user", "content": "x" * 33000}])
    with pytest.raises(ValueError, match="Messages"):
        adapter.complete([{"content": "hello"}])


def test_ask_cli_json_text_and_failed_status(retrieved, monkeypatch, capsys, tmp_path):
    model = FakeModel()
    monkeypatch.setattr("archie.cli.load_source_index", lambda path: (None, {"model": {"revision": "test"}}, None, None))
    monkeypatch.setattr("archie.cli.SentenceEmbedder", lambda **kwargs: object())
    monkeypatch.setattr("archie.cli.retrieve", lambda *args, **kwargs: retrieved)
    monkeypatch.setattr("archie.cli.QwenModel", lambda **kwargs: model)
    args = ["ask", str(tmp_path), "What is App?"]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["claims"]
    assert main(args + ["--format", "text"]) == 0
    assert "src/1.cs:1:1-1:10" in capsys.readouterr().out
    model.value["claims"][0]["evidence_ids"] = ["evidence:99"]
    assert main(args) == 1
    assert json.loads(capsys.readouterr().err)["status"] == "failed"


def test_qwen_explicit_cpu_and_unavailable_cuda(adapter, monkeypatch, tmp_path):
    assert QwenModel(device="cpu", cache_dir=tmp_path).identity["dtype"] == "float32"
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False)))
    assert QwenModel(device="auto", cache_dir=tmp_path).identity["device"] == "cpu"
    with pytest.raises(ValueError, match="CUDA is unavailable"):
        QwenModel(device="cuda", cache_dir=tmp_path)


def test_schema_constraint_prevents_trailing_quote():
    pytest.importorskip("lmformatenforcer")
    from archie.language_model import _schema_constraint

    class CharacterTokenizer:
        eos_token_id = 256
        all_special_ids = [256]
        def __len__(self): return 257
        def encode(self, text, **kwargs): return [ord(char) for char in text]
        def decode(self, ids, **kwargs): return "".join(chr(key) for key in ids)

    tokenizer = CharacterTokenizer()
    constraint = _schema_constraint(tokenizer, {"type": "object", "additionalProperties": False,
                                               "required": ["ok"], "properties": {"ok": {"type": "boolean"}}})
    sequence = [ord("P")]
    for char in '{"ok":true}':
        allowed = constraint(0, SimpleNamespace(tolist=lambda: sequence))
        assert ord(char) in allowed
        sequence.append(ord(char))
    allowed = constraint(0, SimpleNamespace(tolist=lambda: sequence))
    assert tokenizer.eos_token_id in allowed and ord('"') not in allowed
