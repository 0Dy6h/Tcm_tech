import hashlib
import hmac
import json
import secrets
from collections.abc import Mapping
from typing import Any

from app.schemas.rag import RagAnswerResponse

# Process-local by design for the current single-process preview profile. A
# restart invalidates old export payloads instead of accepting unsigned or
# client-modified reviewer artifacts.
_EXPORT_SIGNING_KEY = secrets.token_bytes(32)


def _normalize_json_numbers(value: Any) -> Any:
    """Match browser JSON number roundtrips without coercing other types.

    A browser returns 1.0 as 1 (and -0.0 as 0). Keep every raw field and
    preserve strings / booleans so model defaults and coercions cannot hide
    client modifications during integrity verification.
    """
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [_normalize_json_numbers(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_json_numbers(item) for key, item in value.items()}
    return value


def _canonical_answer_payload(answer: RagAnswerResponse | Mapping[str, Any]) -> bytes:
    if isinstance(answer, RagAnswerResponse):
        payload = answer.model_dump(mode="json", exclude={"integrity_token"})
    else:
        payload = {key: value for key, value in answer.items() if key != "integrity_token"}
    return json.dumps(
        _normalize_json_numbers(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def attach_export_integrity(answer: RagAnswerResponse) -> RagAnswerResponse:
    token = hmac.new(
        _EXPORT_SIGNING_KEY,
        _canonical_answer_payload(answer),
        hashlib.sha256,
    ).hexdigest()
    return answer.model_copy(update={"integrity_token": token})


def has_valid_export_integrity(answer: RagAnswerResponse | Mapping[str, Any]) -> bool:
    token = (
        answer.integrity_token
        if isinstance(answer, RagAnswerResponse)
        else answer.get("integrity_token")
    )
    if (
        not isinstance(token, str)
        or len(token) != 64
        or any(character not in "0123456789abcdef" for character in token)
    ):
        return False
    try:
        canonical_payload = _canonical_answer_payload(answer)
    except (TypeError, ValueError, UnicodeError):
        return False
    expected = hmac.new(
        _EXPORT_SIGNING_KEY,
        canonical_payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(token, expected)
