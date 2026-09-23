import os
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.repositories.protocols import (
        ChunkRepository,
        LiteratureRepository,
        NetworkTaskRepositoryProtocol,
    )

_SAMPLE_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "literature" / "sample_ad_literature.json"
)
_CHUNK_SAMPLE_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "literature" / "sample_ad_chunks.json"
)

_lit_repo_cache: "LiteratureRepository | None" = None
_lit_repo_cache_backend: str | None = None

_chunk_repo_cache: "ChunkRepository | None" = None
_chunk_repo_cache_backend: str | None = None

_nt_repo_cache: "NetworkTaskRepositoryProtocol | None" = None
_nt_repo_cache_backend: str | None = None
_nt_repo_cache_lock = RLock()


def _close_if_sqlite(repo: object | None) -> None:
    """Close a repository connection/pool if it has one.

    JSON/in-memory repositories have no ``close`` method, so this is a no-op
    for them. SQLite repositories expose ``close()`` to release
    local file locks or connection pools.
    """
    close = getattr(repo, "close", None)
    if callable(close):
        close()


def resolve_literature_storage_path() -> Path:
    """
    Return absolute path to runtime literature state file:
    backend/data/runtime/literature_state.json

    On first call:
    - If LITERATURE_RUNTIME_STATE_PATH env var is set, use it as target path
    - If target file already exists, return its path directly
    - If target does not exist, bootstrap from sample (binary copy), then return

    Creates backend/data/runtime/ directory if needed.
    """
    env_path = os.environ.get("LITERATURE_RUNTIME_STATE_PATH")
    if env_path:
        target = Path(env_path)
    else:
        target = Path(__file__).resolve().parents[2] / "data" / "runtime" / "literature_state.json"

    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_SAMPLE_PATH.read_bytes())

    return target


def resolve_chunk_storage_path() -> Path:
    """
    Return absolute path to runtime chunk state file:
    backend/data/runtime/chunk_state.json

    Mirrors resolve_literature_storage_path so uploaded PDF chunks land in
    gitignored runtime state, not in the tracked seed file. Bootstrap is
    binary-identical to sample_ad_chunks.json on first call.

    Env override: CHUNK_RUNTIME_STATE_PATH.
    """
    env_path = os.environ.get("CHUNK_RUNTIME_STATE_PATH")
    if env_path:
        target = Path(env_path)
    else:
        target = Path(__file__).resolve().parents[2] / "data" / "runtime" / "chunk_state.json"

    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_CHUNK_SAMPLE_PATH.read_bytes())

    return target


def resolve_network_tasks_storage_path() -> Path:
    """
    Return absolute path to runtime network task state file:
    backend/data/runtime/network_tasks_state.json

    Network tasks are mutation-only state with no tracked seed, so first-call
    bootstrap writes an empty list "[]\n" instead of copying a sample file.

    Env override: NETWORK_TASKS_RUNTIME_STATE_PATH.
    """
    env_path = os.environ.get("NETWORK_TASKS_RUNTIME_STATE_PATH")
    if env_path:
        target = Path(env_path)
    else:
        target = (
            Path(__file__).resolve().parents[2] / "data" / "runtime" / "network_tasks_state.json"
        )

    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("[]\n", encoding="utf-8")

    return target


def resolve_vector_index_cache_path() -> Path:
    """
    Return absolute path to the chunk vector index cache file:
    backend/data/runtime/vector_index_state.npy

    Unlike literature/chunk runtime files, the vector index is a *derived*
    artifact — first build writes it; missing cache is normal. The companion
    metadata file lives next to it as ``vector_index_state.meta.json``.

    Env override: VECTOR_INDEX_RUNTIME_CACHE_PATH.
    """
    env_path = os.environ.get("VECTOR_INDEX_RUNTIME_CACHE_PATH")
    if env_path:
        target = Path(env_path)
    else:
        target = Path(__file__).resolve().parents[2] / "data" / "runtime" / "vector_index_state.npy"
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def resolve_sqlite_db_path() -> Path:
    """Return path to the SQLite database file.

    Env override: QIYAN_SQLITE_DB_PATH.
    Default: backend/data/runtime/qiyan_state.sqlite3
    """
    env_path = os.environ.get("QIYAN_SQLITE_DB_PATH")
    if env_path:
        return Path(env_path)
    return Path(__file__).resolve().parents[2] / "data" / "runtime" / "qiyan_state.sqlite3"


def get_literature_repository() -> "LiteratureRepository":
    """Factory: return a LiteratureRepository based on QIYAN_STATE_BACKEND.

    - ``"json"`` (default)   → InMemoryLiteratureRepository
    - ``"sqlite"``           → SqliteLiteratureRepository

    Results are cached at module level; call
    :func:`clear_literature_repository_cache` to reset (e.g. in tests).
    """
    global _lit_repo_cache, _lit_repo_cache_backend

    backend = os.environ.get("QIYAN_STATE_BACKEND", "json")

    if _lit_repo_cache is not None and _lit_repo_cache_backend == backend:
        return _lit_repo_cache

    _close_if_sqlite(_lit_repo_cache)

    if backend == "sqlite":
        from app.repositories.sqlite_literature import SqliteLiteratureRepository

        db_path = resolve_sqlite_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _lit_repo_cache = SqliteLiteratureRepository(db_path)
    else:
        from app.repositories.literature import InMemoryLiteratureRepository

        _lit_repo_cache = InMemoryLiteratureRepository(resolve_literature_storage_path())

    _lit_repo_cache_backend = backend
    return _lit_repo_cache


def clear_literature_repository_cache() -> None:
    """Reset the module-level repository cache (for use in tests)."""
    global _lit_repo_cache, _lit_repo_cache_backend
    _close_if_sqlite(_lit_repo_cache)
    _lit_repo_cache = None
    _lit_repo_cache_backend = None


def get_chunk_repository() -> "ChunkRepository":
    """Factory: return a ChunkRepository based on QIYAN_STATE_BACKEND.

    - ``"json"`` (default)   → InMemoryChunkRepository
    - ``"sqlite"``           → SqliteChunkRepository

    Results are cached at module level; call
    :func:`clear_chunk_repository_cache` to reset (e.g. in tests).
    """
    global _chunk_repo_cache, _chunk_repo_cache_backend

    backend = os.environ.get("QIYAN_STATE_BACKEND", "json")

    if _chunk_repo_cache is not None and _chunk_repo_cache_backend == backend:
        return _chunk_repo_cache

    _close_if_sqlite(_chunk_repo_cache)

    if backend == "sqlite":
        from app.repositories.sqlite_chunk import SqliteChunkRepository

        db_path = resolve_sqlite_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _chunk_repo_cache = SqliteChunkRepository(db_path)
    else:
        from app.repositories.chunk import InMemoryChunkRepository

        _chunk_repo_cache = InMemoryChunkRepository(resolve_chunk_storage_path())

    _chunk_repo_cache_backend = backend
    return _chunk_repo_cache


def clear_chunk_repository_cache() -> None:
    """Reset the module-level chunk repository cache (for use in tests)."""
    global _chunk_repo_cache, _chunk_repo_cache_backend
    _close_if_sqlite(_chunk_repo_cache)
    _chunk_repo_cache = None
    _chunk_repo_cache_backend = None


def get_network_task_repository() -> "NetworkTaskRepositoryProtocol":
    """Factory: return a NetworkTaskRepository based on QIYAN_STATE_BACKEND.

    - ``"json"`` (default)   → NetworkTaskRepository (InMemory)
    - ``"sqlite"``           → SqliteNetworkTaskRepository

    Results are cached at module level; call
    :func:`clear_network_task_repository_cache` to reset (e.g. in tests).
    """
    global _nt_repo_cache, _nt_repo_cache_backend

    backend = os.environ.get("QIYAN_STATE_BACKEND", "json")

    with _nt_repo_cache_lock:
        if _nt_repo_cache is not None and _nt_repo_cache_backend == backend:
            return _nt_repo_cache

        _close_if_sqlite(_nt_repo_cache)

        if backend == "sqlite":
            from app.repositories.sqlite_network_tasks import SqliteNetworkTaskRepository

            db_path = resolve_sqlite_db_path()
            db_path.parent.mkdir(parents=True, exist_ok=True)
            _nt_repo_cache = SqliteNetworkTaskRepository(db_path)
        else:
            from app.repositories.network_tasks import NetworkTaskRepository

            _nt_repo_cache = NetworkTaskRepository(resolve_network_tasks_storage_path())

        _nt_repo_cache_backend = backend
        return _nt_repo_cache


def clear_network_task_repository_cache() -> None:
    """Reset the module-level network task repository cache (for use in tests)."""
    global _nt_repo_cache, _nt_repo_cache_backend
    with _nt_repo_cache_lock:
        _close_if_sqlite(_nt_repo_cache)
        _nt_repo_cache = None
        _nt_repo_cache_backend = None
