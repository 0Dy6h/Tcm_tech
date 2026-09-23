"""NLI entailment backend for the opt-in second-stage grounding gate.

Cosine similarity (``score_claim_support``) measures topical relatedness, which
cannot separate a faithful paraphrase from an on-topic fabrication — both are
similar to the cited chunk (see
``docs/evaluations/2026-06-01-threshold-recalibration.md``). An NLI model scores
*entailment* (does the cited chunk entail the claim?), which does separate them
(see ``docs/evaluations/2026-06-01-nli-grounding-spike.md``).

This module mirrors the ``EmbeddingBackend`` env-selection pattern. The gate is
**default-off**: ``select_nli_backend`` returns ``None`` unless
``QIYAN_NLI_BACKEND`` names a real backend. ``TransformersNliBackend`` is a thin
lazy wrapper that imports ``transformers`` + ``torch`` and loads the model only
on first ``entailment`` call, so CI and the default offline path never touch the
heavy dependency.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Protocol, runtime_checkable

_LOGGER = logging.getLogger(__name__)

NLI_BACKEND_ENV_VAR = "QIYAN_NLI_BACKEND"
NLI_MODEL_ENV_VAR = "QIYAN_NLI_MODEL"
DEFAULT_NLI_MODEL = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
_DISABLED_NAMES = {"", "off", "none", "disabled", "false", "0"}


@runtime_checkable
class NliBackend(Protocol):
    name: str

    def entailment(self, premise: str, hypothesis: str) -> float:
        """Return P(premise entails hypothesis) in ``[0, 1]``."""
        ...

    def entailment_batch(self, premises: list[str], hypotheses: list[str]) -> list[float]:
        """Score a batch of (premise, hypothesis) pairs in one forward pass.

        ``premises[i]`` is paired with ``hypotheses[i]``. Callers MUST ensure
        ``len(premises) == len(hypotheses)``. Returns one float per pair.
        """
        ...


def _load_nli_pipeline(model_name: str) -> Any:
    """Import transformers lazily and return a loaded sequence-classification model.

    Patched out in tests so constructing ``TransformersNliBackend`` never imports
    transformers or downloads weights.
    """

    cached = _PIPELINE_CACHE.get(model_name)
    if cached is not None:
        return cached

    import torch  # type: ignore[import-not-found, unused-ignore]
    from transformers import (  # type: ignore[import-not-found, unused-ignore]
        AutoModelForSequenceClassification,
        AutoTokenizer,
    )

    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(model_name)
    model.eval()
    loaded = (tokenizer, model, torch)
    _PIPELINE_CACHE[model_name] = loaded
    return loaded


# Process-wide cache shared by the lifespan warm-up and per-request backends.
_PIPELINE_CACHE: dict[str, Any] = {}


class TransformersNliBackend:
    """Lazy multilingual-NLI wrapper (default ``mDeBERTa-v3-base-mnli-xnli``).

    The model is a 3-way classifier (entailment / neutral / contradiction). We
    expose only the entailment probability; the gate blocks claims whose cited
    chunk does not entail them above a threshold.
    """

    name = "transformers"

    def __init__(self, model_name: str | None = None, max_length: int = 256) -> None:
        resolved = model_name if model_name else os.getenv(NLI_MODEL_ENV_VAR, DEFAULT_NLI_MODEL)
        self.model_name: str = resolved
        self._max_length = max_length
        self._tokenizer: Any = None
        self._model: Any = None
        self._torch: Any = None
        self._entail_index: int | None = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        self._tokenizer, self._model, self._torch = _load_nli_pipeline(self.model_name)
        label_map = {label.lower(): idx for idx, label in self._model.config.id2label.items()}
        # MNLI/XNLI heads label this class "entailment"; fall back to index 0,
        # which is the entailment slot for the mDeBERTa-v3-mnli-xnli family.
        self._entail_index = label_map.get("entailment", 0)

    def entailment(self, premise: str, hypothesis: str) -> float:
        self._ensure_loaded()
        torch = self._torch
        inputs = self._tokenizer(
            premise,
            hypothesis,
            truncation=True,
            max_length=self._max_length,
            return_tensors="pt",
        )
        with torch.no_grad():
            logits = self._model(**inputs).logits[0]
        probs = torch.softmax(logits, dim=-1)
        assert self._entail_index is not None
        return float(probs[self._entail_index].item())

    def entailment_batch(self, premises: list[str], hypotheses: list[str]) -> list[float]:
        """Score multiple (premise, hypothesis) pairs in a single forward pass.

        Uses the tokenizer's list-pair API to batch all pairs together, which
        reduces per-pair latency from O(n) to O(1) model forward passes.
        """
        if not premises:
            return []
        self._ensure_loaded()
        torch = self._torch
        inputs = self._tokenizer(
            premises,
            hypotheses,
            truncation=True,
            max_length=self._max_length,
            padding=True,
            return_tensors="pt",
        )
        with torch.no_grad():
            logits = self._model(**inputs).logits
        probs = torch.softmax(logits, dim=-1)
        assert self._entail_index is not None
        return [float(p[self._entail_index].item()) for p in probs]


_BACKENDS: dict[str, type[NliBackend]] = {
    TransformersNliBackend.name: TransformersNliBackend,
}


def select_nli_backend(name: str | None = None) -> NliBackend | None:
    """Return the configured NLI backend, or ``None`` when the gate is disabled.

    Precedence: explicit ``name`` argument → ``QIYAN_NLI_BACKEND`` env → disabled.
    Disabled values (``off`` / ``none`` / empty / unset) and unknown names both
    return ``None`` so a typo never silently engages or breaks the gate; the gate
    is purely additive and off by default.
    """

    raw = name if name is not None else os.getenv(NLI_BACKEND_ENV_VAR, "")
    candidate = raw.strip().lower()
    if candidate in _DISABLED_NAMES:
        return None
    backend_cls = _BACKENDS.get(candidate)
    if backend_cls is None:
        _LOGGER.warning(
            "Unknown %s=%r; NLI grounding gate stays disabled",
            NLI_BACKEND_ENV_VAR,
            raw,
        )
        return None
    return backend_cls()
