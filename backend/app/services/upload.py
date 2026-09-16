import hashlib
from typing import BinaryIO, Protocol

from app.core.config import get_settings
from app.schemas.upload import StoredUpload
from app.services.literature import attach_pdf_metadata, build_pdf_upload_id, get_literature_item
from app.services.pdf_storage import build_storage_path, persist_pdf_contents


class PdfUpload(Protocol):
    filename: str | None
    content_type: str | None
    file: BinaryIO


def store_pdf_upload(file: PdfUpload, literature_id: str) -> StoredUpload:
    if file.content_type != "application/pdf":
        raise ValueError("Only PDF uploads are supported")
    if get_literature_item(literature_id) is None:
        raise LookupError("Literature item not found")

    contents = file.file.read()
    if not contents.startswith(b"%PDF-"):
        raise ValueError("The uploaded file must contain PDF bytes")
    storage_dir = get_settings().upload_storage_dir
    storage_dir.mkdir(parents=True, exist_ok=True)
    file_name = file.filename or "upload.pdf"
    pdf_upload_id = build_pdf_upload_id(
        literature_id, file_name, content_sha256=hashlib.sha256(contents).hexdigest()
    )
    storage_path = build_storage_path(storage_dir, pdf_upload_id, file_name)
    persist_pdf_contents(storage_path, contents)

    item = attach_pdf_metadata(literature_id, file_name, pdf_upload_id=pdf_upload_id)
    if item is None:
        raise LookupError("Literature item not found")

    return StoredUpload(
        literature_id=literature_id,
        pdf_upload_id=pdf_upload_id,
        file_name=file_name,
        content_type=file.content_type,
        file_size=len(contents),
        storage_path=str(storage_path),
        pdf_parse_status=item.pdf_parse_status or "pending",
    )
