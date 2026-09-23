"""Background preload of optional real embedding / NLI models.

No-op unless ``QIYAN_EMBEDDING_BACKEND`` names a real model backend or
``QIYAN_NLI_BACKEND`` enables NLI; the defaults (hashing / off) never import
heavy ML libraries. Readiness is reported via ``/health`` extra keys.
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

# None = model path disabled (nothing to warm); False = loading/failed; True = ready.
_state: dict[str, bool | None] = {"embedding_ready": None, "nli_ready": None}
_lock = threading.Lock()


def warmup_status() -> dict[str, bool | None]:
    with _lock:
        return dict(_state)


def _set(key: str, value: bool | None) -> None:
    with _lock:
        _state[key] = value


def _warm_embedding() -> None:
    from app.services.retrieval.embedding import HashingEmbeddingBackend, select_embedding_backend

    backend = select_embedding_backend()
    if isinstance(backend, HashingEmbeddingBackend):
        return
    _set("embedding_ready", False)
    try:
        backend.encode(["warmup"])
        _set("embedding_ready", True)
        logger.info("embedding model warm-up finished: %s", backend.name)
    except Exception:  # noqa: BLE001 - warm-up must never crash the server
        logger.exception("embedding model warm-up failed; will load lazily on first use")


def _warm_nli(nli_backend_name: str) -> None:
    from app.services.nli import select_nli_backend

    backend = select_nli_backend(nli_backend_name)
    if backend is None:
        return
    _set("nli_ready", False)
    try:
        backend.entailment("预热", "预热")
        _set("nli_ready", True)
        logger.info("NLI model warm-up finished: %s", backend.name)
    except Exception:  # noqa: BLE001
        logger.exception("NLI model warm-up failed; will load lazily on first use")


def start_model_warmup(nli_backend_name: str) -> threading.Thread | None:
    """Start a daemon thread preloading enabled models; return None when nothing to do."""

    from app.services.nli import select_nli_backend
    from app.services.retrieval.embedding import HashingEmbeddingBackend, select_embedding_backend

    embedding_enabled = not isinstance(select_embedding_backend(), HashingEmbeddingBackend)
    nli_enabled = select_nli_backend(nli_backend_name) is not None
    if not embedding_enabled and not nli_enabled:
        return None
    if embedding_enabled:
        _set("embedding_ready", False)
    if nli_enabled:
        _set("nli_ready", False)

    def run() -> None:
        if embedding_enabled:
            _warm_embedding()
        if nli_enabled:
            _warm_nli(nli_backend_name)

    thread = threading.Thread(target=run, name="qiyan-model-warmup", daemon=True)
    thread.start()
    return thread
