"""Local Qwen generation in a subprocess with a hard execution deadline."""
import json
import re
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

from .contracts import validate_generation_limits

MODEL_ID = "Qwen/Qwen3-4B-Instruct-2507"
MODEL_REVISION = "cdbee75f17c01a7cc42f958dc650907174af0554"
MODEL_CACHE = Path(__file__).resolve().parents[1] / "artifacts/models"


class QwenModel:
    def __init__(self, *, device="auto", cache_dir=MODEL_CACHE, revision=MODEL_REVISION):
        try:
            import torch
            from huggingface_hub import hf_hub_download
            from transformers import AutoTokenizer
            decoder_version = version("lm-format-enforcer")
        except ImportError as error:
            raise ValueError('Install local model dependencies: python -m pip install -e ".[retrieval,answering]"') from error
        self.device = "cuda" if device == "auto" and torch.cuda.is_available() else device
        if self.device == "auto":
            self.device = "cpu"
        if self.device not in {"cpu", "cuda"}:
            raise ValueError("Model device must be auto, cpu, or cuda")
        if self.device == "cuda" and not torch.cuda.is_available():
            raise ValueError("CUDA is unavailable; use --device cpu or install compatible PyTorch")
        self.cache_dir = str(Path(cache_dir).resolve())
        try:
            config = hf_hub_download(MODEL_ID, "config.json", revision=revision, cache_dir=self.cache_dir)
            resolved = Path(config).parent.name
            if not re.fullmatch(r"[a-f0-9]{40}", resolved):
                raise ValueError("Qwen revision could not be resolved")
            self.tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, revision=resolved,
                cache_dir=self.cache_dir, trust_remote_code=False)
        except (OSError, RuntimeError) as error:
            raise ValueError(f"Qwen tokenizer failed: {error}") from error
        self.identity = {"model_id": MODEL_ID, "revision": resolved,
                         "runtime_version": (f"transformers:{version('transformers')} torch:{version('torch')} "
                                             f"lm-format-enforcer:{decoder_version}"),
                         "device": self.device, "dtype": "bfloat16" if self.device == "cuda" else "float32"}

    def _render(self, messages):
        if (not isinstance(messages, list) or not messages
                or any(not isinstance(message, dict) or set(message) != {"role", "content"}
                       or message["role"] not in {"system", "user", "assistant"}
                       or not isinstance(message["content"], str) for message in messages)):
            raise ValueError("Messages must contain role and text content")
        return self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)

    def count_tokens(self, messages):
        return len(self.tokenizer(self._render(messages), add_special_tokens=False)["input_ids"])

    def complete(self, messages, *, max_new_tokens=1024, timeout_seconds=180, response_schema=None):
        validate_generation_limits(max_new_tokens, timeout_seconds)
        if response_schema is not None and not isinstance(response_schema, dict):
            raise ValueError("response_schema must be a JSON Schema object")
        prompt = self._render(messages)
        input_tokens = len(self.tokenizer(prompt, add_special_tokens=False)["input_ids"])
        if input_tokens + max_new_tokens > min(self.tokenizer.model_max_length, 32768):
            raise ValueError("Prompt and output exceed the local generation context limit")
        request = {"prompt": prompt, "revision": self.identity["revision"], "device": self.device,
                   "cache_dir": self.cache_dir, "max_new_tokens": max_new_tokens, "response_schema": response_schema}
        started = perf_counter()
        try:
            process = subprocess.run([sys.executable, "-m", "archie.language_model"],
                                     input=json.dumps(request), capture_output=True, text=True,
                                     timeout=timeout_seconds)
        except subprocess.TimeoutExpired as error:
            raise ValueError(f"Local generation exceeded {timeout_seconds} seconds") from error
        if process.returncode:
            raise ValueError(f"Qwen worker exited {process.returncode}: {process.stderr[-2000:].strip()}")
        result = json.loads(process.stdout)
        if (not isinstance(result, dict) or set(result) != {"text", "input_tokens", "output_tokens", "finish_reason"}
                or not isinstance(result["text"], str)
                or type(result["input_tokens"]) is not int or result["input_tokens"] != input_tokens
                or type(result["output_tokens"]) is not int or not 0 <= result["output_tokens"] <= max_new_tokens
                or result["finish_reason"] not in {"stop", "length"}):
            raise ValueError("Invalid Qwen worker response")
        return {**result, "latency_ms": (perf_counter() - started) * 1000}


def _schema_constraint(tokenizer, schema):
    # The library's HF bridge imports a Transformers 4-only module; use its runtime-neutral API.
    from lmformatenforcer import JsonSchemaParser, TokenEnforcer, TokenEnforcerTokenizerData

    zero = tokenizer.encode("0", add_special_tokens=False)[0]
    special = set(tokenizer.all_special_ids)
    pieces = []
    for key in range(len(tokenizer)):
        if key not in special:
            alone = tokenizer.decode([key], clean_up_tokenization_spaces=False)
            context = tokenizer.decode([zero, key], clean_up_tokenization_spaces=False)[1:]
            pieces.append((key, context, len(context) > len(alone)))
    def decode(keys):
        return tokenizer.decode(keys, clean_up_tokenization_spaces=False).rstrip("\ufffd")
    data = TokenEnforcerTokenizerData(pieces, decode, tokenizer.eos_token_id, False, len(tokenizer))
    enforcer = TokenEnforcer(data, JsonSchemaParser(schema))
    def allowed(batch_id, keys):
        return enforcer.get_allowed_tokens(keys.tolist()).allowed_tokens
    return allowed


def _worker():
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    request = json.load(sys.stdin)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, revision=request["revision"],
        cache_dir=request["cache_dir"], trust_remote_code=False)
    model = AutoModelForCausalLM.from_pretrained(MODEL_ID, revision=request["revision"],
        cache_dir=request["cache_dir"], trust_remote_code=False,
        dtype=torch.bfloat16 if request["device"] == "cuda" else torch.float32).to(request["device"]).eval()
    inputs = tokenizer(request["prompt"], add_special_tokens=False, return_tensors="pt").to(request["device"])
    count = inputs["input_ids"].shape[-1]
    if count + request["max_new_tokens"] > min(model.config.max_position_embeddings, 32768):
        raise ValueError("Worker input exceeds generation context limit")
    generation = {}
    if request.get("response_schema") is not None:
        generation["prefix_allowed_tokens_fn"] = _schema_constraint(tokenizer, request["response_schema"])
    with torch.inference_mode():
        output = model.generate(**inputs, max_new_tokens=request["max_new_tokens"], do_sample=False,
                                pad_token_id=tokenizer.eos_token_id, **generation)
    tokens = output[0][count:]
    eos = model.generation_config.eos_token_id
    eos = {eos} if isinstance(eos, int) else set(eos or [])
    print(json.dumps({"text": tokenizer.decode(tokens, skip_special_tokens=True), "input_tokens": count,
                      "output_tokens": len(tokens), "finish_reason": "stop" if len(tokens) and tokens[-1].item() in eos else "length"}))


if __name__ == "__main__":
    try:
        _worker()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
