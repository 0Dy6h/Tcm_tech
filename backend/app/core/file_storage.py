"""Atomic local writes and shared locks for the single-process preview store."""

import os
from pathlib import Path
from tempfile import mkstemp
from threading import Lock, RLock
from weakref import WeakValueDictionary

_LOCKS_GUARD = Lock()
_PATH_LOCKS: WeakValueDictionary[Path, RLock] = WeakValueDictionary()


def path_lock(path: Path) -> RLock:
    """Canonical paths share a lock across repository instances in this process."""
    key = path.resolve()
    with _LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, RLock())


def atomic_write_bytes(path: Path, contents: bytes) -> None:
    """Publish a complete same-directory file, preserving the old file on failure."""
    descriptor, name = mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_text(path: Path, contents: str, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, contents.encode(encoding))
