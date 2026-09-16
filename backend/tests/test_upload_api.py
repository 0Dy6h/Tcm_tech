import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.repositories.chunk import InMemoryChunkRepository
from app.repositories.literature import InMemoryLiteratureRepository


def reset_sample_data(original_path: Path, temp_path: Path) -> None:
    temp_path.write_text(original_path.read_text(encoding="utf-8"), encoding="utf-8")


def write_extractable_pdf(path: Path, text: str) -> None:
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, NumberObject, StreamObject

    writer = PdfWriter()
    page = writer.add_blank_page(612, 792)
    content_bytes = f"BT /F1 12 Tf 100 700 Td ({text}) Tj ET".encode("ascii")
    content_stream = StreamObject()
    content_stream._data = content_bytes
    content_stream[NameObject("/Length")] = NumberObject(len(content_bytes))
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Contents")] = writer._add_object(content_stream)
    page[NameObject("/Resources")] = writer._add_object(
        DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
    )
    with path.open("wb") as file:
        writer.write(file)


def test_pdf_upload_endpoint_persists_file_and_attaches_metadata(monkeypatch, tmp_path: Path):
    from app.services import literature as literature_service

    original_path = (
        Path(__file__).resolve().parents[1] / "data" / "literature" / "sample_ad_literature.json"
    )
    temp_data_path = tmp_path / "sample_ad_literature.json"
    reset_sample_data(original_path, temp_data_path)

    monkeypatch.setenv("UPLOAD_STORAGE_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()
    literature_service._REPOSITORY = InMemoryLiteratureRepository(temp_data_path)

    client = TestClient(app)

    response = client.post(
        "/api/uploads/pdf",
        data={"literature_id": "cn-ad-gbs-001"},
        files={
            "file": ("ad-evidence.pdf", b"%PDF-1.4\nmock pdf bytes\n", "application/pdf"),
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["literature_id"] == "cn-ad-gbs-001"
    assert re.fullmatch(r"pdf-[a-f0-9]{64}", payload["pdf_upload_id"])
    assert payload["file_name"] == "ad-evidence.pdf"
    assert payload["pdf_parse_status"] == "pending"
    assert payload["storage_path"].endswith(f"{payload['pdf_upload_id']}.pdf")

    persisted = json.loads(temp_data_path.read_text(encoding="utf-8"))
    first = next(item for item in persisted if item["id"] == "cn-ad-gbs-001")
    assert first["pdf_upload_id"] == payload["pdf_upload_id"]
    assert first["pdf_file_name"] == "ad-evidence.pdf"
    assert first["pdf_parse_status"] == "pending"
    assert first["pdf_parse_message"] is None
    assert first["pdf_parse_started_at"] is None
    assert first["pdf_parse_finished_at"] is None
    assert first["last_parse_trigger"] is None
    assert first["parse_attempt_count"] == 0

    stored_file = Path(payload["storage_path"])
    assert stored_file.exists()
    assert stored_file.read_bytes() == b"%PDF-1.4\nmock pdf bytes\n"


def test_pdf_upload_endpoint_normalizes_storage_suffix_to_pdf_for_uppercase_filename(
    monkeypatch, tmp_path: Path
):
    from app.services import literature as literature_service

    original_path = (
        Path(__file__).resolve().parents[1] / "data" / "literature" / "sample_ad_literature.json"
    )
    temp_data_path = tmp_path / "sample_ad_literature.json"
    reset_sample_data(original_path, temp_data_path)

    monkeypatch.setenv("UPLOAD_STORAGE_DIR", str(tmp_path / "uploads"))
    literature_service._REPOSITORY = InMemoryLiteratureRepository(temp_data_path)

    client = TestClient(app)

    response = client.post(
        "/api/uploads/pdf",
        data={"literature_id": "cn-ad-gbs-001"},
        files={
            "file": ("AD-EVIDENCE.PDF", b"%PDF-1.4\nmock uppercase suffix\n", "application/pdf"),
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["storage_path"].endswith(f"{payload['pdf_upload_id']}.pdf")

    download_response = client.get(f"/api/uploads/pdf/{payload['pdf_upload_id']}")
    assert download_response.status_code == 200
    assert download_response.headers["content-type"] == "application/pdf"
    assert download_response.content == b"%PDF-1.4\nmock uppercase suffix\n"


def test_pdf_upload_endpoint_ignores_legacy_auto_parse_field_and_keeps_pending(
    monkeypatch, tmp_path: Path
):
    from app.services import literature as literature_service

    original_path = (
        Path(__file__).resolve().parents[1] / "data" / "literature" / "sample_ad_literature.json"
    )
    temp_data_path = tmp_path / "sample_ad_literature.json"
    reset_sample_data(original_path, temp_data_path)

    monkeypatch.setenv("UPLOAD_STORAGE_DIR", str(tmp_path / "uploads"))
    literature_service._REPOSITORY = InMemoryLiteratureRepository(temp_data_path)

    client = TestClient(app)

    response = client.post(
        "/api/uploads/pdf",
        data={"literature_id": "cn-ad-gbs-001", "auto_parse": "true"},
        files={
            "file": ("ad-evidence.pdf", b"%PDF-1.4\nmock pdf bytes\n", "application/pdf"),
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["pdf_parse_status"] == "pending"

    persisted = json.loads(temp_data_path.read_text(encoding="utf-8"))
    first = next(item for item in persisted if item["id"] == "cn-ad-gbs-001")
    assert first["pdf_parse_status"] == "pending"
    assert first["last_parse_trigger"] is None
    assert first["parse_attempt_count"] == 0


def test_pdf_upload_endpoint_ignores_legacy_auto_parse_field_for_fail_file_and_keeps_pending(
    monkeypatch, tmp_path: Path
):
    from app.services import literature as literature_service

    original_path = (
        Path(__file__).resolve().parents[1] / "data" / "literature" / "sample_ad_literature.json"
    )
    temp_data_path = tmp_path / "sample_ad_literature.json"
    reset_sample_data(original_path, temp_data_path)

    monkeypatch.setenv("UPLOAD_STORAGE_DIR", str(tmp_path / "uploads"))
    literature_service._REPOSITORY = InMemoryLiteratureRepository(temp_data_path)

    client = TestClient(app)

    response = client.post(
        "/api/uploads/pdf",
        data={"literature_id": "cn-ad-gbs-001", "auto_parse": "true"},
        files={
            "file": ("ad-fail-evidence.pdf", b"%PDF-1.4\nmock pdf bytes\n", "application/pdf"),
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["pdf_parse_status"] == "pending"

    persisted = json.loads(temp_data_path.read_text(encoding="utf-8"))
    first = next(item for item in persisted if item["id"] == "cn-ad-gbs-001")
    assert first["pdf_parse_status"] == "pending"
    assert first["last_parse_trigger"] is None
    assert first["parse_attempt_count"] == 0


def test_fake_parser_endpoint_marks_pending_upload_as_parsed_with_message_timestamps_and_auto_trigger(
    monkeypatch, tmp_path: Path
):
    from app.services import fake_parser as fake_parser_service
    from app.services import literature as literature_service

    original_path = (
        Path(__file__).resolve().parents[1] / "data" / "literature" / "sample_ad_literature.json"
    )
    original_chunk_path = (
        Path(__file__).resolve().parents[1] / "data" / "literature" / "sample_ad_chunks.json"
    )
    temp_data_path = tmp_path / "sample_ad_literature.json"
    temp_chunk_path = tmp_path / "sample_ad_chunks.json"
    reset_sample_data(original_path, temp_data_path)
    reset_sample_data(original_chunk_path, temp_chunk_path)

    repository = InMemoryLiteratureRepository(temp_data_path)
    repository.update_pdf_metadata(
        literature_id="cn-ad-gbs-001",
        pdf_upload_id="pdf-cn-ad-gbs-001-ad-evidence-pdf",
        pdf_file_name="ad-evidence.pdf",
        pdf_parse_status="pending",
    )

    monkeypatch.setattr(literature_service, "_REPOSITORY", repository)
    monkeypatch.setattr(
        fake_parser_service,
        "_CHUNK_REPOSITORY",
        InMemoryChunkRepository(temp_chunk_path),
    )

    client = TestClient(app)

    response = client.post(
        "/api/uploads/pdf/auto-parse",
        json={"literature_id": "cn-ad-gbs-001", "file_name": "ad-evidence.pdf"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["pdf_parse_status"] == "parsed"
    assert payload["pdf_parse_message"] == "Mock parser completed successfully"
    assert payload["pdf_parse_started_at"] is not None
    assert payload["pdf_parse_finished_at"] is not None
    assert payload["last_parse_trigger"] == "auto"
    assert payload["parse_attempt_count"] == 1

    persisted_chunks = json.loads(temp_chunk_path.read_text(encoding="utf-8"))
    uploaded_chunk = next(
        item
        for item in persisted_chunks
        if item["chunk_id"] == "chunk-pdf-cn-ad-gbs-001-ad-evidence-pdf-uploaded"
    )
    assert uploaded_chunk["literature_id"] == "cn-ad-gbs-001"
    assert uploaded_chunk["source_type"] == "uploaded_pdf"
    assert uploaded_chunk["pdf_upload_id"] == "pdf-cn-ad-gbs-001-ad-evidence-pdf"
    assert "上传 PDF ad-evidence.pdf 已完成解析" in uploaded_chunk["text"]


def test_fake_parser_endpoint_uses_extracted_pdf_text_for_parse_result_preview(
    monkeypatch, tmp_path: Path
):
    from app.services import fake_parser as fake_parser_service
    from app.services import literature as literature_service

    original_path = (
        Path(__file__).resolve().parents[1] / "data" / "literature" / "sample_ad_literature.json"
    )
    original_chunk_path = (
        Path(__file__).resolve().parents[1] / "data" / "literature" / "sample_ad_chunks.json"
    )
    temp_data_path = tmp_path / "sample_ad_literature.json"
    temp_chunk_path = tmp_path / "sample_ad_chunks.json"
    reset_sample_data(original_path, temp_data_path)
    reset_sample_data(original_chunk_path, temp_chunk_path)

    upload_dir = tmp_path / "uploads"
    pdf_upload_id = "pdf-cn-ad-gbs-001-ad-evidence-pdf"
    stored_pdf_path = upload_dir / f"{pdf_upload_id}.pdf"
    upload_dir.mkdir()
    write_extractable_pdf(stored_pdf_path, "Atopic dermatitis PDF preview evidence text")

    repository = InMemoryLiteratureRepository(temp_data_path)
    repository.update_pdf_metadata(
        literature_id="cn-ad-gbs-001",
        pdf_upload_id=pdf_upload_id,
        pdf_file_name="ad-evidence.pdf",
        pdf_parse_status="pending",
    )

    monkeypatch.setenv("UPLOAD_STORAGE_DIR", str(upload_dir))
    get_settings.cache_clear()
    monkeypatch.setattr(literature_service, "_REPOSITORY", repository)
    monkeypatch.setattr(
        fake_parser_service,
        "_CHUNK_REPOSITORY",
        InMemoryChunkRepository(temp_chunk_path),
    )

    client = TestClient(app)

    response = client.post(
        "/api/uploads/pdf/auto-parse",
        json={"literature_id": "cn-ad-gbs-001", "file_name": "ad-evidence.pdf"},
    )

    assert response.status_code == 200
    parse_result = response.json()["pdf_parse_result"]
    assert parse_result["preview_text"] == "Atopic dermatitis PDF preview evidence text"
    assert parse_result["extraction_method"] == "pypdf-text-preview"
    assert parse_result["quality_warning"] is None


def test_fake_parser_endpoint_warns_when_extracted_pdf_text_has_numeric_garbling(
    monkeypatch, tmp_path: Path
):
    from app.services import fake_parser as fake_parser_service
    from app.services import literature as literature_service

    original_path = (
        Path(__file__).resolve().parents[1] / "data" / "literature" / "sample_ad_literature.json"
    )
    original_chunk_path = (
        Path(__file__).resolve().parents[1] / "data" / "literature" / "sample_ad_chunks.json"
    )
    temp_data_path = tmp_path / "sample_ad_literature.json"
    temp_chunk_path = tmp_path / "sample_ad_chunks.json"
    reset_sample_data(original_path, temp_data_path)
    reset_sample_data(original_chunk_path, temp_chunk_path)

    upload_dir = tmp_path / "uploads"
    pdf_upload_id = "pdf-cn-ad-gbs-001-garbled-pdf"
    stored_pdf_path = upload_dir / f"{pdf_upload_id}.pdf"
    upload_dir.mkdir()
    stored_pdf_path.write_bytes(b"%PDF-1.4\nplaceholder bytes; extractor is monkeypatched\n")

    repository = InMemoryLiteratureRepository(temp_data_path)
    repository.update_pdf_metadata(
        literature_id="cn-ad-gbs-001",
        pdf_upload_id=pdf_upload_id,
        pdf_file_name="garbled.pdf",
        pdf_parse_status="pending",
    )

    monkeypatch.setenv("UPLOAD_STORAGE_DIR", str(upload_dir))
    get_settings.cache_clear()
    monkeypatch.setattr(literature_service, "_REPOSITORY", repository)
    monkeypatch.setattr(
        literature_service,
        "extract_pdf_preview_text",
        lambda _path: "中国中医药信息杂志 \x00\x00\x00\x00 年 第 \x00 卷 表 \x00\x00",
    )
    monkeypatch.setattr(
        fake_parser_service,
        "_CHUNK_REPOSITORY",
        InMemoryChunkRepository(temp_chunk_path),
    )

    client = TestClient(app)

    response = client.post(
        "/api/uploads/pdf/auto-parse",
        json={"literature_id": "cn-ad-gbs-001", "file_name": "garbled.pdf"},
    )

    assert response.status_code == 200
    parse_result = response.json()["pdf_parse_result"]
    assert parse_result["extraction_method"] == "pypdf-text-preview"
    assert parse_result["quality_warning"] == (
        "检测到抽取文本可能存在数字或表格乱码，请对照原始 PDF 核对关键数值。"
    )


def test_fake_parser_endpoint_keeps_placeholder_preview_when_pdf_text_extraction_fails(
    monkeypatch, tmp_path: Path
):
    from app.services import fake_parser as fake_parser_service
    from app.services import literature as literature_service

    original_path = (
        Path(__file__).resolve().parents[1] / "data" / "literature" / "sample_ad_literature.json"
    )
    original_chunk_path = (
        Path(__file__).resolve().parents[1] / "data" / "literature" / "sample_ad_chunks.json"
    )
    temp_data_path = tmp_path / "sample_ad_literature.json"
    temp_chunk_path = tmp_path / "sample_ad_chunks.json"
    reset_sample_data(original_path, temp_data_path)
    reset_sample_data(original_chunk_path, temp_chunk_path)

    upload_dir = tmp_path / "uploads"
    pdf_upload_id = "pdf-cn-ad-gbs-001-ad-evidence-pdf"
    stored_pdf_path = upload_dir / f"{pdf_upload_id}.pdf"
    upload_dir.mkdir()
    stored_pdf_path.write_bytes(b"%PDF-1.4\nnot enough structure for pypdf text extraction\n")

    repository = InMemoryLiteratureRepository(temp_data_path)
    repository.update_pdf_metadata(
        literature_id="cn-ad-gbs-001",
        pdf_upload_id=pdf_upload_id,
        pdf_file_name="ad-evidence.pdf",
        pdf_parse_status="pending",
    )

    monkeypatch.setenv("UPLOAD_STORAGE_DIR", str(upload_dir))
    get_settings.cache_clear()
    monkeypatch.setattr(literature_service, "_REPOSITORY", repository)
    monkeypatch.setattr(
        fake_parser_service,
        "_CHUNK_REPOSITORY",
        InMemoryChunkRepository(temp_chunk_path),
    )

    client = TestClient(app)

    response = client.post(
        "/api/uploads/pdf/auto-parse",
        json={"literature_id": "cn-ad-gbs-001", "file_name": "ad-evidence.pdf"},
    )

    assert response.status_code == 200
    parse_result = response.json()["pdf_parse_result"]
    assert (
        parse_result["preview_text"]
        == "已读取上传 PDF 文件，当前提供文件级解析预览；正文抽取将在后续接入。"
    )
    assert parse_result["extraction_method"] == "file-metadata-placeholder"
    assert parse_result["quality_warning"] is None


def test_fake_parser_endpoint_marks_pending_upload_as_failed_with_message_timestamps_and_auto_trigger(
    monkeypatch, tmp_path: Path
):
    from app.services import fake_parser as fake_parser_service
    from app.services import literature as literature_service

    original_path = (
        Path(__file__).resolve().parents[1] / "data" / "literature" / "sample_ad_literature.json"
    )
    original_chunk_path = (
        Path(__file__).resolve().parents[1] / "data" / "literature" / "sample_ad_chunks.json"
    )
    temp_data_path = tmp_path / "sample_ad_literature.json"
    temp_chunk_path = tmp_path / "sample_ad_chunks.json"
    reset_sample_data(original_path, temp_data_path)
    reset_sample_data(original_chunk_path, temp_chunk_path)

    repository = InMemoryLiteratureRepository(temp_data_path)
    repository.update_pdf_metadata(
        literature_id="cn-ad-gbs-001",
        pdf_upload_id="pdf-cn-ad-gbs-001-ad-fail-evidence-pdf",
        pdf_file_name="ad-fail-evidence.pdf",
        pdf_parse_status="pending",
    )

    monkeypatch.setattr(literature_service, "_REPOSITORY", repository)
    monkeypatch.setattr(
        fake_parser_service,
        "_CHUNK_REPOSITORY",
        InMemoryChunkRepository(temp_chunk_path),
    )

    client = TestClient(app)

    response = client.post(
        "/api/uploads/pdf/auto-parse",
        json={"literature_id": "cn-ad-gbs-001", "file_name": "ad-fail-evidence.pdf"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["pdf_parse_status"] == "failed"
    assert payload["pdf_parse_message"] == "Mock parser flagged file as failed"
    assert payload["pdf_parse_started_at"] is not None
    assert payload["pdf_parse_finished_at"] is not None
    assert payload["last_parse_trigger"] == "auto"
    assert payload["parse_attempt_count"] == 1

    persisted_chunks = json.loads(temp_chunk_path.read_text(encoding="utf-8"))
    assert all(
        item["chunk_id"] != "chunk-pdf-cn-ad-gbs-001-ad-fail-evidence-pdf-uploaded"
        for item in persisted_chunks
    )


def test_manual_parse_status_endpoint_marks_manual_trigger(monkeypatch, tmp_path: Path):
    from app.services import literature as literature_service

    original_path = (
        Path(__file__).resolve().parents[1] / "data" / "literature" / "sample_ad_literature.json"
    )
    temp_data_path = tmp_path / "sample_ad_literature.json"
    reset_sample_data(original_path, temp_data_path)

    repository = InMemoryLiteratureRepository(temp_data_path)
    repository.update_pdf_metadata(
        literature_id="cn-ad-gbs-001",
        pdf_upload_id="pdf-cn-ad-gbs-001-ad-evidence-pdf",
        pdf_file_name="ad-evidence.pdf",
        pdf_parse_status="pending",
    )

    monkeypatch.setattr(literature_service, "_REPOSITORY", repository)

    client = TestClient(app)

    response = client.post(
        "/api/literature/pdf-parse-status",
        json={"literature_id": "cn-ad-gbs-001", "pdf_parse_status": "parsed"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["pdf_parse_status"] == "parsed"
    assert payload["last_parse_trigger"] == "manual"
    assert payload["parse_attempt_count"] == 1


def test_manual_parse_status_endpoint_increments_attempt_count_after_auto_parse(
    monkeypatch, tmp_path: Path
):
    from app.services import fake_parser as fake_parser_service
    from app.services import literature as literature_service

    original_path = (
        Path(__file__).resolve().parents[1] / "data" / "literature" / "sample_ad_literature.json"
    )
    original_chunk_path = (
        Path(__file__).resolve().parents[1] / "data" / "literature" / "sample_ad_chunks.json"
    )
    temp_data_path = tmp_path / "sample_ad_literature.json"
    temp_chunk_path = tmp_path / "sample_ad_chunks.json"
    reset_sample_data(original_path, temp_data_path)
    reset_sample_data(original_chunk_path, temp_chunk_path)

    repository = InMemoryLiteratureRepository(temp_data_path)
    repository.update_pdf_metadata(
        literature_id="cn-ad-gbs-001",
        pdf_upload_id="pdf-cn-ad-gbs-001-ad-evidence-pdf",
        pdf_file_name="ad-evidence.pdf",
        pdf_parse_status="pending",
    )

    monkeypatch.setattr(literature_service, "_REPOSITORY", repository)
    monkeypatch.setattr(
        fake_parser_service,
        "_CHUNK_REPOSITORY",
        InMemoryChunkRepository(temp_chunk_path),
    )

    client = TestClient(app)

    auto_response = client.post(
        "/api/uploads/pdf/auto-parse",
        json={"literature_id": "cn-ad-gbs-001", "file_name": "ad-evidence.pdf"},
    )
    assert auto_response.status_code == 200
    assert auto_response.json()["parse_attempt_count"] == 1

    manual_response = client.post(
        "/api/literature/pdf-parse-status",
        json={"literature_id": "cn-ad-gbs-001", "pdf_parse_status": "failed"},
    )
    assert manual_response.status_code == 200
    payload = manual_response.json()
    assert payload["last_parse_trigger"] == "manual"
    assert payload["parse_attempt_count"] == 2


def test_pdf_upload_endpoint_returns_404_for_unknown_literature_id_and_does_not_persist_file(
    monkeypatch, tmp_path: Path
):
    from app.services import literature as literature_service

    original_path = (
        Path(__file__).resolve().parents[1] / "data" / "literature" / "sample_ad_literature.json"
    )
    temp_data_path = tmp_path / "sample_ad_literature.json"
    reset_sample_data(original_path, temp_data_path)

    upload_dir = tmp_path / "uploads"
    monkeypatch.setenv("UPLOAD_STORAGE_DIR", str(upload_dir))
    literature_service._REPOSITORY = InMemoryLiteratureRepository(temp_data_path)

    client = TestClient(app)

    response = client.post(
        "/api/uploads/pdf",
        data={"literature_id": "unknown"},
        files={
            "file": ("ad-evidence.pdf", b"%PDF-1.4\nmock pdf bytes\n", "application/pdf"),
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Literature item not found"}
    assert not upload_dir.exists() or list(upload_dir.iterdir()) == []


def test_pdf_upload_endpoint_stores_with_upload_id_based_name_to_avoid_filename_collisions(
    monkeypatch, tmp_path: Path
):
    from app.services import literature as literature_service

    original_path = (
        Path(__file__).resolve().parents[1] / "data" / "literature" / "sample_ad_literature.json"
    )
    temp_data_path = tmp_path / "sample_ad_literature.json"
    reset_sample_data(original_path, temp_data_path)

    upload_dir = tmp_path / "uploads"
    monkeypatch.setenv("UPLOAD_STORAGE_DIR", str(upload_dir))
    literature_service._REPOSITORY = InMemoryLiteratureRepository(temp_data_path)

    client = TestClient(app)

    response = client.post(
        "/api/uploads/pdf",
        data={"literature_id": "cn-ad-gbs-001"},
        files={
            "file": ("review.pdf", b"%PDF-1.4\nmock pdf bytes\n", "application/pdf"),
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert re.fullmatch(r"pdf-[a-f0-9]{64}", payload["pdf_upload_id"])
    assert payload["storage_path"].endswith(f"{payload['pdf_upload_id']}.pdf")

    stored_file = Path(payload["storage_path"])
    assert stored_file.exists()
    assert stored_file.name == f"{payload['pdf_upload_id']}.pdf"


def test_pdf_download_endpoint_returns_uploaded_file_by_upload_id(monkeypatch, tmp_path: Path):
    from app.services import literature as literature_service

    original_path = (
        Path(__file__).resolve().parents[1] / "data" / "literature" / "sample_ad_literature.json"
    )
    temp_data_path = tmp_path / "sample_ad_literature.json"
    reset_sample_data(original_path, temp_data_path)

    upload_dir = tmp_path / "uploads"
    monkeypatch.setenv("UPLOAD_STORAGE_DIR", str(upload_dir))
    literature_service._REPOSITORY = InMemoryLiteratureRepository(temp_data_path)

    client = TestClient(app)

    upload_response = client.post(
        "/api/uploads/pdf",
        data={"literature_id": "cn-ad-gbs-001"},
        files={
            "file": ("review.pdf", b"%PDF-1.4\nmock pdf bytes\n", "application/pdf"),
        },
    )
    assert upload_response.status_code == 201
    upload_payload = upload_response.json()

    download_response = client.get(f"/api/uploads/pdf/{upload_payload['pdf_upload_id']}")

    assert download_response.status_code == 200
    assert download_response.headers["content-type"] == "application/pdf"
    assert download_response.headers["content-disposition"].startswith("inline;")
    assert download_response.content == b"%PDF-1.4\nmock pdf bytes\n"


def test_pdf_download_endpoint_returns_404_for_missing_upload(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("UPLOAD_STORAGE_DIR", str(tmp_path / "uploads"))

    client = TestClient(app)

    response = client.get("/api/uploads/pdf/pdf-cn-ad-gbs-001-missing-pdf")

    assert response.status_code == 404
    assert response.json() == {"detail": "PDF upload not found"}
