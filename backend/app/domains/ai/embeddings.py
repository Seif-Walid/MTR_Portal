"""Text → vector. Claude has no embeddings endpoint, so the local build uses a
small free ONNX model through fastembed (runs on CPU, downloads ~130 MB once).
Anything with an `embed(texts) -> list[list[float]]` and a `name` works, so a
hosted embedder (Voyage, Gemini) can replace it later by setting."""

from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache
from typing import Protocol

from app.core.config import settings


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def normalise(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class FastEmbedder:
    def __init__(self, model: str) -> None:
        from fastembed import TextEmbedding  # optional dependency (requirements-ai.txt)

        self.name = model
        self._model = TextEmbedding(model_name=model)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [normalise([float(x) for x in v]) for v in self._model.passage_embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        """Retrieval models (bge) embed a search query with an instruction prefix."""
        return normalise([float(x) for x in next(iter(self._model.query_embed([text])))])


class HashEmbedder:
    """Deterministic bag-of-words hashing — no semantics, used by tests and as
    the fallback when no model is installed. `synonyms` maps a word to a
    canonical token so tests can prove the synonym path end to end."""

    def __init__(self, dims: int = 256, synonyms: dict[str, str] | None = None) -> None:
        self.name = f"hash-{dims}"
        self.dims = dims
        self.synonyms = synonyms or {}

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.dims
            for word in re.findall(r"[a-z0-9]+", text.lower()):
                word = self.synonyms.get(word, word)
                h = int(hashlib.md5(word.encode()).hexdigest(), 16)
                vec[h % self.dims] += 1.0
            out.append(normalise(vec))
        return out


_override: Embedder | None = None


def set_embedder(embedder: Embedder | None) -> None:
    """Tests inject a deterministic embedder here."""
    global _override
    _override = embedder
    _default.cache_clear()


@lru_cache(maxsize=1)
def _default() -> Embedder:
    if settings.ai_embedder == "fastembed":
        try:
            return FastEmbedder(settings.ai_embed_model)
        except ImportError:
            pass  # fastembed not installed: degrade to lexical-ish hashing
    return HashEmbedder()


def get_embedder() -> Embedder:
    return _override or _default()
