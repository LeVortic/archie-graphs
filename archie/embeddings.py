"""Local Sentence Transformers adapter; device choice does not change stored identity."""
from importlib.metadata import version
from pathlib import Path
import re

MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"


class SentenceEmbedder:
    def __init__(self, *, device="auto", cache_dir=None, revision=None):
        try:
            import torch
            from sentence_transformers import SentenceTransformer
            from huggingface_hub import hf_hub_download
        except ImportError as error:
            raise ValueError('Install retrieval dependencies: python -m pip install -e ".[retrieval]"') from error
        selected = "cuda" if device == "auto" and torch.cuda.is_available() else device
        if selected == "auto":
            selected = "cpu"
        if selected not in {"cpu", "cuda"}:
            raise ValueError("Embedding device must be auto, cpu, or cuda")
        if selected == "cuda" and not torch.cuda.is_available():
            raise ValueError("CUDA is unavailable; install a compatible PyTorch build or select --device cpu")
        try:
            config_path = hf_hub_download(MODEL_ID, "config.json", revision=revision, cache_dir=cache_dir)
            resolved = Path(config_path).parent.name
            if not re.fullmatch(r"[a-f0-9]{40}", resolved):
                raise ValueError("Embedding model revision could not be resolved")
            self.model = SentenceTransformer(MODEL_ID, device=selected, cache_folder=cache_dir,
                                             revision=resolved, trust_remote_code=False)
            self.device = selected
            self.max_tokens = self.model.max_seq_length
            dimensions = len(self.embed(["embedding runtime check"])[0])
            self.identity = {"model_id": MODEL_ID, "revision": resolved,
                             "runtime": "sentence-transformers", "runtime_version": (f"sentence-transformers:{version('sentence-transformers')} "
                                                 f"transformers:{version('transformers')} "
                                                 f"torch:{version('torch').split('+')[0]}"),
                             "dimensions": dimensions,
                             "max_tokens": self.max_tokens, "normalized": True}
        except (OSError, RuntimeError) as error:
            raise ValueError(f"Local embedding runtime failed on {selected}: {error}") from error

    def count_tokens(self, text):
        return len(self.model.tokenizer(text, truncation=False)["input_ids"])

    def embed(self, texts):
        if any(self.count_tokens(text) > self.max_tokens for text in texts):
            raise ValueError("Text exceeds the embedding model token limit")
        try:
            return self.model.encode(texts, batch_size=32, normalize_embeddings=True,
                                     show_progress_bar=False).tolist()
        except RuntimeError as error:
            raise ValueError(f"Embedding failed on {self.device}: {error}") from error
