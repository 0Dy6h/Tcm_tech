"""Embedding backend abstraction (C3 slice 2/5).

Mirrors the ``LLMProvider`` / ``RetrievalProvider`` env-selection pattern. The
default ``HashingEmbeddingBackend`` is deterministic, offline, and dim=128 — CI
and the test suite never touch ``sentence-transformers`` and never download the
~95 MB ``BAAI/bge-small-zh-v1.5`` weights. ``SentenceTransformerEmbeddingBackend``
is a thin lazy wrapper that imports + loads the model only on first ``encode``.

The hashing scheme: lowercase token → md5 → 16 bytes interpreted as a ±1 sign
pattern across the 128 dims, summed across tokens, then L2 normalised. Empty
texts collapse to ``e_0`` so downstream code never sees a zero vector.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from typing import Any, Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt

_LOGGER = logging.getLogger(__name__)

EMBEDDING_BACKEND_ENV_VAR = "QIYAN_EMBEDDING_BACKEND"
DEFAULT_EMBEDDING_BACKEND_NAME = "hashing"

EmbeddingMatrix = npt.NDArray[np.float32]

_TOKEN_PATTERN = re.compile(r"[\w]+")


def _tokenize_for_hashing(text: str) -> list[str]:
    normalized = text.lower().strip()
    tokens = _TOKEN_PATTERN.findall(normalized)
    for char in normalized:
        if "一" <= char <= "鿿":
            tokens.append(char)
    return tokens


@runtime_checkable
class EmbeddingBackend(Protocol):
    name: str
    dim: int

    def encode(self, texts: list[str]) -> EmbeddingMatrix: ...


class HashingEmbeddingBackend:
    """Deterministic md5 → ±1 → L2-normalised embedding (zero downloads)."""

    name = "hashing"
    dim = 128

    def encode(self, texts: list[str]) -> EmbeddingMatrix:
        vectors = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            tokens = _tokenize_for_hashing(text)
            vec = vectors[row]
            if not tokens:
                vec[0] = 1.0
                continue
            for token in tokens:
                digest = hashlib.md5(token.encode("utf-8")).digest()
                for i in range(self.dim):
                    byte = digest[i % 16]
                    bit = (byte >> (i % 8)) & 1
                    vec[i] += 1.0 if bit else -1.0
            norm = float(np.linalg.norm(vec))
            if norm == 0.0:
                vec[0] = 1.0
            else:
                vec /= norm
        return vectors


def _load_sentence_transformer(model_name: str) -> Any:
    """Import sentence-transformers lazily and return a loaded model.

    Patched out in tests so constructing ``SentenceTransformerEmbeddingBackend``
    never imports or downloads the model.
    """

    cached = _MODEL_CACHE.get(model_name)
    if cached is not None:
        return cached

    from sentence_transformers import (  # type: ignore[import-untyped, import-not-found, unused-ignore]
        SentenceTransformer,
    )

    model = SentenceTransformer(model_name)
    _MODEL_CACHE[model_name] = model
    return model


# Process-wide cache so the lifespan warm-up and per-request backends share one
# loaded model instead of reloading weights for every new backend instance.
_MODEL_CACHE: dict[str, Any] = {}


class SentenceTransformerEmbeddingBackend:
    """Lazy ``BAAI/bge-small-zh-v1.5`` wrapper for dev/prod embeddings."""

    name = "bge"
    dim = 512
    model_name = "BAAI/bge-small-zh-v1.5"

    def __init__(self) -> None:
        self._model: Any = None

    def encode(self, texts: list[str]) -> EmbeddingMatrix:
        if self._model is None:
            self._model = _load_sentence_transformer(self.model_name)
        raw = self._model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return np.asarray(raw, dtype=np.float32)


class MultilingualBgeM3EmbeddingBackend:
    """Lazy ``BAAI/bge-m3`` wrapper for cross-lingual (CN ↔ EN) embeddings.

    Opt-in via ``QIYAN_EMBEDDING_BACKEND=multilingual_bge_m3``; default backend
    remains ``hashing``. First ``encode`` triggers a ~1.4GB one-time download to
    ``~/.cache/huggingface/``. Selection rationale lives in
    ``docs/evaluations/2026-06-04-multilingual-embedding-model-selection.md``.
    """

    name = "multilingual_bge_m3"
    dim = 1024
    model_name = "BAAI/bge-m3"

    def __init__(self) -> None:
        self._model: Any = None

    def encode(self, texts: list[str]) -> EmbeddingMatrix:
        if self._model is None:
            self._model = _load_sentence_transformer(self.model_name)
        raw = self._model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return np.asarray(raw, dtype=np.float32)


_BACKENDS: dict[str, type[EmbeddingBackend]] = {
    HashingEmbeddingBackend.name: HashingEmbeddingBackend,
    SentenceTransformerEmbeddingBackend.name: SentenceTransformerEmbeddingBackend,
    MultilingualBgeM3EmbeddingBackend.name: MultilingualBgeM3EmbeddingBackend,
}


def select_embedding_backend(name: str | None = None) -> EmbeddingBackend:
    """Return the configured embedding backend, falling back to hashing.

    Precedence: explicit ``name`` argument → ``QIYAN_EMBEDDING_BACKEND`` env →
    ``HashingEmbeddingBackend``. Unknown names log a warning and fall back so
    a typo never breaks retrieval; the fall-back is always safe to run offline.
    """

    raw = name if name is not None else os.getenv(EMBEDDING_BACKEND_ENV_VAR, "")
    candidate = raw.strip().lower()
    if not candidate:
        return HashingEmbeddingBackend()
    backend_cls = _BACKENDS.get(candidate)
    if backend_cls is None:
        _LOGGER.warning(
            "Unknown %s=%r; falling back to %s",
            EMBEDDING_BACKEND_ENV_VAR,
            raw,
            DEFAULT_EMBEDDING_BACKEND_NAME,
        )
        return HashingEmbeddingBackend()
    return backend_cls()
