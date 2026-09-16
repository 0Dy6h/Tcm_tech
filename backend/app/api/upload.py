from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from app.schemas.literature import LiteratureItem
from app.schemas.upload import FakePdfAutoParseRequest, StoredUpload
from app.services.fake_parser import auto_parse_uploaded_pdf
from app.services.pdf_storage import resolve_stored_pdf_path
from app.services.upload import store_pdf_upload

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

# Maximum PDF file size: 20MB (sub-limit of global 50MB request limit)
MAX_PDF_SIZE = 20 * 1024 * 1024


@router.post("/pdf", response_model=StoredUpload, status_code=status.HTTP_201_CREATED)
def upload_pdf_endpoint(
    literature_id: str = Form(),
    file: UploadFile = File(),
) -> StoredUpload:
    # Check file size before processing
    if file.file:
        file.file.seek(0, 2)  # Seek to end
        size = file.file.tell()
        file.file.seek(0)  # Reset to beginning

        if size > MAX_PDF_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"PDF 文件过大，最大允许 {MAX_PDF_SIZE // 1024 // 1024}MB",
            )

    try:
        return store_pdf_upload(file, literature_id)
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/pdf/{pdf_upload_id}", response_class=FileResponse)
def download_pdf_endpoint(pdf_upload_id: str) -> FileResponse:
    storage_path = resolve_stored_pdf_path(pdf_upload_id)
    if storage_path is None:
        raise HTTPException(status_code=404, detail="PDF upload not found")
    return FileResponse(
        storage_path,
        media_type="application/pdf",
        filename=storage_path.name,
        content_disposition_type="inline",
    )


@router.post("/pdf/auto-parse", response_model=LiteratureItem)
def auto_parse_pdf_endpoint(request: FakePdfAutoParseRequest = Body()) -> LiteratureItem:
    try:
        return auto_parse_uploaded_pdf(
            request.literature_id, request.file_name, request.pdf_upload_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
