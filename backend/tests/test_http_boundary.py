"""真实 HTTP 入口的跨站写入、DNS rebinding 与分块请求边界。"""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.core.config import get_settings


@pytest.mark.parametrize("origin", ["https://attacker.invalid", "null"])
def test_foreign_simple_multipart_is_rejected_before_pdf_is_stored(origin):
    with TestClient(main.app) as client:
        response = client.post(
            "/api/uploads/pdf",
            headers={"Origin": origin},
            data={"literature_id": "cn-ad-gbs-001"},
            files={"file": ("cross-site.pdf", b"%PDF-1.4\nprobe\n", "application/pdf")},
        )
    assert response.status_code == 403
    assert not list(get_settings().upload_storage_dir.glob("*.pdf"))


def test_open_preview_rejects_rebound_hostname_even_without_origin():
    with TestClient(main.app, base_url="http://attacker.invalid") as client:
        response = client.get("/api/literature/search", params={"q": "AD"})
    assert response.status_code == 403


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3100",
        "http://127.0.0.1:3100",
        "http://127.0.0.1",
    ],
)
def test_documented_local_origins_can_read(origin):
    with TestClient(main.app) as client:
        response = client.get(
            "/api/literature/search", params={"q": "AD"}, headers={"Origin": origin}
        )
    assert response.status_code == 200


def test_chunked_multipart_is_limited_before_upload_persistence(monkeypatch):
    monkeypatch.setattr(main, "MAX_REQUEST_SIZE", 512)
    body = (
        b'--boundary\r\nContent-Disposition: form-data; name="literature_id"\r\n\r\n'
        b"cn-ad-gbs-001\r\n--boundary\r\n"
        b'Content-Disposition: form-data; name="file"; filename="chunked.pdf"\r\n'
        b"Content-Type: application/pdf\r\n\r\n%PDF-1.4\n" + b"x" * 600 + b"\r\n--boundary--\r\n"
    )
    with TestClient(main.app) as client:
        response = client.post(
            "/api/uploads/pdf",
            headers={"Content-Type": "multipart/form-data; boundary=boundary"},
            content=iter([body[:128], body[128:]]),
        )
    assert response.status_code == 413
    assert not list(get_settings().upload_storage_dir.glob("*.pdf"))


@pytest.mark.parametrize("declared", [None, b"1"])
def test_limit_counts_actual_asgi_chunks_and_stops_reading(monkeypatch, declared):
    monkeypatch.setattr(main, "MAX_REQUEST_SIZE", 8)
    reads = []
    output = []
    consumed = []
    chunks = iter([b"12345", b"67890", b"must-not-be-read"])

    async def receive():
        chunk = next(chunks)
        reads.append(chunk)
        return {"type": "http.request", "body": chunk, "more_body": True}

    async def downstream(scope, receive, send):
        while True:
            message = await receive()
            consumed.append(message["body"])
            if not message.get("more_body"):
                break

    async def send(message):
        output.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [] if declared is None else [(b"content-length", declared)],
    }
    asyncio.run(main.RequestSizeLimitMiddleware(downstream)(scope, receive, send))
    assert output[0]["status"] == 413
    assert json.loads(output[1]["body"])["detail"]
    assert reads == [b"12345", b"67890"]
    assert consumed == [b"12345"]
