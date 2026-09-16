"""Integration tests for POST /api/rag/answer/export endpoint."""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app

DISCLAIMER = "非诊断结论、需结合临床。"

_SAMPLE_ANSWER_PAYLOAD: dict[str, object] = {
    "question": "特应性皮炎和肠-脑-皮肤轴有什么关系？",
    "answer": "基于当前检索到的证据片段，已优先返回与问题最相关的文献。",
    "disclaimer": DISCLAIMER,
    "answered_at": "2026-06-04T07:42:11.123456+00:00",
    "provider_name": "deterministic",
    "input_tokens": None,
    "output_tokens": None,
    "retrieval": {
        "applied_source": "all",
        "applied_top_k": 2,
        "available_citation_count": 16,
        "strategy": "keyword",
    },
    "grounding": {
        "status": "skipped",
        "policy": "structured_claim_refs_v3",
        "checked": False,
        "blocked_reason": None,
        "allowed_evidence_refs": ["chunk-cn-ad-gbs-001-abstract"],
        "matched_evidence_refs": [],
        "unsupported_evidence_refs": [],
        "claim_count": 0,
        "cited_claim_count": 0,
        "structured_claims": [],
        "provider_native_grounding": False,
        "tool_name": None,
        "tool_call_count": 0,
    },
    "citations": [
        {
            "literature_id": "cn-ad-gbs-001",
            "chunk_id": "chunk-cn-ad-gbs-001-abstract",
            "title": "肠-脑-皮肤轴与特应性皮炎中医证候研究",
            "source": "CNKI curated AD sample",
            "snippet": "围绕特应性皮炎、肠-脑-皮肤轴与中医证候关联进行综述。",
            "quote": None,
            "reason": "gut_skin_axis, tcm_syndrome",
            "confidence": 0.86,
            "source_type": "sample",
            "pdf_upload_id": None,
            "related_entity_ids": [],
        }
    ],
    "sli": None,
}


def _request_signed_answer(client: TestClient, question: str) -> dict[str, object]:
    response = client.post(
        "/api/rag/answer",
        json={"question": question, "source": "all", "top_k": 2},
    )
    assert response.status_code == 200
    payload: dict[str, object] = response.json()
    assert payload["integrity_token"]
    return payload


def test_rag_answer_export_endpoint_rejects_unsigned_client_payload() -> None:
    client = TestClient(app)

    response = client.post("/api/rag/answer/export", json=_SAMPLE_ANSWER_PAYLOAD)

    assert response.status_code == 409
    assert response.json() == {"detail": "RAG answer export integrity check failed"}


def test_rag_answer_export_endpoint_rejects_modified_signed_payload() -> None:
    client = TestClient(app)
    payload = _request_signed_answer(client, "特应性皮炎和肠-脑-皮肤轴有什么关系？")
    payload["answer"] = "被客户端篡改的伪造结论"

    response = client.post("/api/rag/answer/export", json=payload)

    assert response.status_code == 409
    assert response.json() == {"detail": "RAG answer export integrity check failed"}


def test_rag_answer_export_endpoint_rejects_signed_payload_with_default_field_removed() -> None:
    client = TestClient(app)
    payload = _request_signed_answer(client, "特应性皮炎和肠-脑-皮肤轴有什么关系？")
    del payload["input_tokens"]

    response = client.post("/api/rag/answer/export", json=payload)

    assert response.status_code == 409
    assert response.json() == {"detail": "RAG answer export integrity check failed"}


def test_rag_answer_export_endpoint_rejects_signed_payload_with_required_field_removed() -> None:
    client = TestClient(app)
    payload = _request_signed_answer(client, "特应性皮炎和肠-脑-皮肤轴有什么关系？")
    del payload["question"]

    response = client.post("/api/rag/answer/export", json=payload)

    assert response.status_code == 409
    assert response.json() == {"detail": "RAG answer export integrity check failed"}


def test_rag_answer_export_endpoint_rejects_signed_payload_with_unknown_top_level_field() -> None:
    client = TestClient(app)
    payload = _request_signed_answer(client, "特应性皮炎和肠-脑-皮肤轴有什么关系？")
    payload["client_note"] = "不能加入已签名导出"

    response = client.post("/api/rag/answer/export", json=payload)

    assert response.status_code == 409
    assert response.json() == {"detail": "RAG answer export integrity check failed"}


def test_rag_answer_export_endpoint_rejects_signed_payload_with_unknown_citation_field() -> None:
    client = TestClient(app)
    payload = _request_signed_answer(client, "特应性皮炎和肠-脑-皮肤轴有什么关系？")
    citations = payload["citations"]
    assert isinstance(citations, list)
    assert isinstance(citations[0], dict)
    citations[0]["client_note"] = "不能加入已签名引用"

    response = client.post("/api/rag/answer/export", json=payload)

    assert response.status_code == 409
    assert response.json() == {"detail": "RAG answer export integrity check failed"}


def test_rag_answer_export_endpoint_rejects_signed_payload_with_unknown_grounding_field() -> None:
    client = TestClient(app)
    payload = _request_signed_answer(client, "特应性皮炎和肠-脑-皮肤轴有什么关系？")
    grounding = payload["grounding"]
    assert isinstance(grounding, dict)
    grounding["client_note"] = "不能加入已签名 grounding"

    response = client.post("/api/rag/answer/export", json=payload)

    assert response.status_code == 409
    assert response.json() == {"detail": "RAG answer export integrity check failed"}


def test_rag_answer_export_endpoint_returns_plain_text_markdown() -> None:
    client = TestClient(app)
    payload = _request_signed_answer(client, "特应性皮炎和肠-脑-皮肤轴有什么关系？")

    response = client.post("/api/rag/answer/export", json=payload)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "charset=utf-8" in response.headers["content-type"]

    body = response.text
    assert body.startswith("# Qiyan Nexus RAG 答案导出")
    assert DISCLAIMER in body
    assert "特应性皮炎和肠-脑-皮肤轴有什么关系？" in body
    assert "literature_id：cn-ad-gbs-001" in body
    assert str(payload["answered_at"]) in body
    assert "应用来源：全部文献" in body
    assert "应用 top_k：2" in body
    assert "Provider：deterministic" in body


@pytest.mark.parametrize("suffix", ["", "/docx"])
def test_signed_answer_survives_browser_json_number_roundtrip(suffix: str) -> None:
    client = TestClient(app)
    payload = _request_signed_answer(client, "特应性皮炎的皮肤屏障机制是什么？")

    def javascript_json_number(value: str) -> int | float:
        number = float(value)
        return int(number) if number.is_integer() else number

    # JSON.parse / JSON.stringify serialize 0.0 and 1.0 as 0 and 1. The
    # browser sends those numerically identical values back for both exports.
    serialized = json.dumps(payload)
    browser_payload = json.loads(serialized, parse_float=javascript_json_number)
    assert json.dumps(browser_payload) != serialized
    response = client.post(f"/api/rag/answer/export{suffix}", json=browser_payload)

    assert response.status_code == 200
    if suffix:
        assert response.content.startswith(b"PK")
    else:
        assert DISCLAIMER in response.text


@pytest.mark.parametrize("replacement", ["2", True, 3])
def test_export_still_rejects_changed_numeric_types_or_values(replacement: object) -> None:
    client = TestClient(app)
    payload = _request_signed_answer(client, "特应性皮炎的皮肤屏障机制是什么？")
    retrieval = payload["retrieval"]
    assert isinstance(retrieval, dict)
    retrieval["applied_top_k"] = replacement

    response = client.post("/api/rag/answer/export", json=payload)

    assert response.status_code == 409


@pytest.mark.parametrize("token", ["篡" * 64, "z" * 64])
def test_export_rejects_malformed_integrity_tokens_without_server_error(token: str) -> None:
    client = TestClient(app)
    payload = _request_signed_answer(client, "特应性皮炎的皮肤屏障机制是什么？")
    payload["integrity_token"] = token

    response = client.post("/api/rag/answer/export", json=payload)

    assert response.status_code == 409


@pytest.mark.parametrize("replacement", [float("nan"), float("inf"), "\ud800"])
def test_export_rejects_nonserializable_signed_fields_without_server_error(
    replacement: object,
) -> None:
    client = TestClient(app)
    payload = _request_signed_answer(client, "特应性皮炎的皮肤屏障机制是什么？")
    payload["answer"] = replacement

    response = client.post(
        "/api/rag/answer/export",
        content=json.dumps(payload),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 409


def test_rag_answer_export_endpoint_handles_empty_citations() -> None:
    client = TestClient(app)
    payload = _request_signed_answer(client, "高血压一线降压药怎么选？")
    assert payload["citations"] == []

    response = client.post("/api/rag/answer/export", json=payload)

    assert response.status_code == 200
    body = response.text
    assert "（当前回答没有可核对的引用证据。）" in body
    assert DISCLAIMER in body


def test_rag_answer_export_endpoint_rejects_malformed_payload() -> None:
    client = TestClient(app)

    response = client.post("/api/rag/answer/export", json={"question": "incomplete"})

    assert response.status_code == 422
