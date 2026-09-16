"""Upload snapshots must remain readable and parsing must bind to one snapshot."""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.services import literature


def upload(client, name, contents):
    return client.post(
        "/api/uploads/pdf",
        data={"literature_id": "cn-ad-gbs-001"},
        files={"file": (name, contents, "application/pdf")},
    )


@pytest.mark.parametrize("names", [("review.pdf", "review.pdf"), ("a+b.pdf", "a-b.pdf")])
def test_reupload_never_changes_the_bytes_behind_an_existing_citation(names):
    before = b"%PDF-1.4\nfirst frozen evidence\n"
    after = b"%PDF-1.4\nsecond frozen evidence\n"
    with TestClient(app) as client:
        first = upload(client, names[0], before)
        second = upload(client, names[1], after)
        assert first.status_code == second.status_code == 201
        first_id = first.json()["pdf_upload_id"]
        second_id = second.json()["pdf_upload_id"]
        assert first_id != second_id
        assert client.get(f"/api/uploads/pdf/{first_id}").content == before
        assert client.get(f"/api/uploads/pdf/{second_id}").content == after


def test_long_upload_filename_still_produces_a_downloadable_snapshot():
    contents = b"%PDF-1.4\nlong filename\n"
    with TestClient(app) as client:
        response = upload(client, "evidence-" * 18 + ".pdf", contents)
        assert response.status_code == 201
        upload_id = response.json()["pdf_upload_id"]
        downloaded = client.get(f"/api/uploads/pdf/{upload_id}")
        assert downloaded.status_code == 200
        assert downloaded.content == contents


@pytest.mark.parametrize("contents", [b"", b"<html>not a PDF</html>"])
def test_declared_pdf_mime_type_cannot_persist_non_pdf_bytes(contents):
    with TestClient(app) as client:
        response = upload(client, "spoofed.pdf", contents)
        assert response.status_code == 415
    assert not list(get_settings().upload_storage_dir.glob("*.pdf"))
    assert literature.get_literature_item("cn-ad-gbs-001").pdf_upload_id is None


def test_stale_parse_request_is_rejected_without_marking_a_replacement_pdf():
    with TestClient(app) as client:
        first = upload(client, "first.pdf", b"%PDF-1.4\nfirst\n").json()
        second = upload(client, "second.pdf", b"%PDF-1.4\nsecond\n").json()
        response = client.post(
            "/api/uploads/pdf/auto-parse",
            json={
                "literature_id": "cn-ad-gbs-001",
                "file_name": first["file_name"],
                "pdf_upload_id": first["pdf_upload_id"],
            },
        )
        assert response.status_code == 409
        item = client.get("/api/literature/cn-ad-gbs-001").json()
        assert item["pdf_upload_id"] == second["pdf_upload_id"]
        assert item["pdf_parse_status"] == "pending"
        assert item["parse_attempt_count"] == 0


def test_upload_during_extraction_cannot_attach_the_old_preview_to_the_new_pdf(monkeypatch):
    with TestClient(app) as client:
        first = upload(client, "first.pdf", b"%PDF-1.4\nfirst\n").json()
        replacement = {}

        def replace_while_parsing(_item):
            replacement.update(upload(client, "second.pdf", b"%PDF-1.4\nsecond\n").json())
            return None

        monkeypatch.setattr(literature, "build_pdf_parse_result", replace_while_parsing)
        response = client.post(
            "/api/uploads/pdf/auto-parse",
            json={
                "literature_id": "cn-ad-gbs-001",
                "file_name": first["file_name"],
                "pdf_upload_id": first["pdf_upload_id"],
            },
        )
        assert response.status_code == 409
        item = client.get("/api/literature/cn-ad-gbs-001").json()
        assert item["pdf_upload_id"] == replacement["pdf_upload_id"]
        assert item["pdf_parse_status"] == "pending"
        assert item["pdf_parse_result"] is None
        assert item["parse_attempt_count"] == 0


def test_upload_storage_failure_keeps_the_previous_snapshot(monkeypatch):
    with TestClient(app, raise_server_exceptions=False) as client:
        first = upload(client, "review.pdf", b"%PDF-1.4\noriginal\n").json()
        stored = Path(first["storage_path"])
        original = stored.read_bytes()
        replace = os.replace

        def fail_before_file_publish(source, destination):
            if Path(destination).parent == stored.parent:
                raise OSError("synthetic disk failure")
            return replace(source, destination)

        monkeypatch.setattr(os, "replace", fail_before_file_publish)
        failed = upload(client, "replacement.pdf", b"%PDF-1.4\nreplacement\n")
        assert failed.status_code == 500
        assert stored.read_bytes() == original
        item = client.get("/api/literature/cn-ad-gbs-001").json()
        assert item["pdf_upload_id"] == first["pdf_upload_id"]
        assert list(stored.parent.glob("*.tmp")) == []
