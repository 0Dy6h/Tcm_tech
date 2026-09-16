from app.repositories.runtime_storage import get_chunk_repository
from app.schemas.literature import LiteratureItem
from app.services.literature import update_pdf_parse_status

_CHUNK_REPOSITORY = get_chunk_repository()


def resolve_fake_parse_status(file_name: str) -> str:
    return "failed" if "fail" in file_name.lower() else "parsed"


def build_uploaded_pdf_chunk_id(pdf_upload_id: str) -> str:
    return f"chunk-{pdf_upload_id}-uploaded"


def build_mock_uploaded_pdf_chunk_text(
    item: LiteratureItem, file_name: str
) -> tuple[str, str, list[str]]:
    evidence_tags = ["uploaded_pdf", "pdf_parse", "atopic_dermatitis"]
    if item.language == "en":
        text = (
            f"Uploaded PDF {file_name} was parsed for {item.title}. "
            "The mock parser extracted an atopic dermatitis evidence note for RAG retrieval and citation testing."
        )
        quote = "mock parser extracted an atopic dermatitis evidence note"
        return text, quote, evidence_tags

    text = (
        f"上传 PDF {file_name} 已完成解析，关联文献《{item.title}》。"
        "Mock parser 提取了特应性皮炎证据片段，用于验证上传 PDF 可进入检索、RAG 问答和引用卡片。"
    )
    quote = "Mock parser 提取了特应性皮炎证据片段"
    return text, quote, evidence_tags


def upsert_uploaded_pdf_chunk(item: LiteratureItem, file_name: str) -> None:
    if not item.pdf_upload_id:
        return
    text, quote, evidence_tags = build_mock_uploaded_pdf_chunk_text(item, file_name)
    _CHUNK_REPOSITORY.upsert_uploaded_pdf_chunk(
        chunk_id=build_uploaded_pdf_chunk_id(item.pdf_upload_id),
        literature_id=item.id,
        pdf_upload_id=item.pdf_upload_id,
        text=text,
        source_quote=quote,
        evidence_tags=evidence_tags,
    )


def auto_parse_uploaded_pdf(
    literature_id: str, file_name: str, pdf_upload_id: str | None = None
) -> LiteratureItem:
    status, item = update_pdf_parse_status(
        literature_id,
        resolve_fake_parse_status(file_name),
        trigger="auto",
        expected_pdf_upload_id=pdf_upload_id,
        expected_file_name=file_name,
    )
    if status == "not_found":
        raise LookupError("Literature item not found")
    if status == "missing_metadata":
        raise ValueError("PDF metadata not attached")
    if status == "conflict":
        raise ValueError("PDF upload changed; reload the current PDF before parsing")
    if item is None:
        raise LookupError("Literature item not found")
    if item.pdf_parse_status == "parsed":
        upsert_uploaded_pdf_chunk(item, file_name)
    return item
