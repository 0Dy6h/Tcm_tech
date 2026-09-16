import re
from pathlib import Path

from app.core.config import get_settings
from app.core.file_storage import atomic_write_bytes, path_lock

# PDF upload ID pattern: only alphanumeric, underscore, hyphen (no dots to prevent traversal)
# Length limit: 1-100 characters after "pdf-" prefix
_PDF_UPLOAD_ID_PATTERN = re.compile(r"^pdf-[a-zA-Z0-9_-]{1,100}$")


def build_storage_path(storage_dir: Path, pdf_upload_id: str, file_name: str) -> Path:
    return storage_dir / f"{pdf_upload_id}.pdf"


def persist_pdf_contents(storage_path: Path, contents: bytes) -> None:
    """A content-bound upload ID never replaces a different evidence snapshot."""
    with path_lock(storage_path):
        if storage_path.exists():
            if storage_path.read_bytes() != contents:
                raise ValueError("Stored PDF integrity mismatch")
            return
        atomic_write_bytes(storage_path, contents)


def resolve_stored_pdf_path(pdf_upload_id: str) -> Path | None:
    if not _PDF_UPLOAD_ID_PATTERN.fullmatch(pdf_upload_id):
        return None

    storage_dir = get_settings().upload_storage_dir.resolve()
    storage_path = (storage_dir / f"{pdf_upload_id}.pdf").resolve()
    if storage_path.parent != storage_dir:
        return None
    if not storage_path.is_file():
        return None
    return storage_path
