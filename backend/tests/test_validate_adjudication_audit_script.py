"""Independent validator tests for the adjudication audit HMAC stream.

``scripts/validate_adjudication_audit.py`` re-derives the chain from persisted
state with zero shared code. These tests prove it accepts genuinely produced
streams (including real repository files for both backends) and rejects every
tampering of the audited era: edited decisions, edited reviewer identity,
edited timestamps, stripped or forged tags, deletions, reorderings, duplicate
ids and a wrong key.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from app.core.audit_hmac import AUDIT_KEY_ENV, derive_adjudication_audit_hmac
from app.repositories.network_tasks import NetworkTaskRepository
from app.repositories.sqlite_network_tasks import SqliteNetworkTaskRepository
from app.schemas.network import NetworkTargetAdjudication
from scripts.validate_adjudication_audit import main, validate_tasks

KEY = "k" * 32
TASK_ID = "network-audit-target"
ROW_ID = "disease-" + "a" * 64


def _event(index: int, task_id: str, prev: str | None) -> dict[str, Any]:
    event: dict[str, Any] = {
        "adjudication_id": f"adjudication-{index:064x}",
        "lineage_row_id": ROW_ID,
        "decision": "included" if index % 2 == 0 else "excluded",
        "reason": None,
        "decided_at": f"2026-09-28T1{index}:00:00+00:00",
        "reviewer_id": "reviewer-a",
        "omics_accession": None,
        "omics_canonical_symbol": None,
        "omics_log2fc": None,
        "omics_adj_p_value": None,
        "audit_hmac": None,
    }
    payload = {key: value for key, value in event.items() if key != "audit_hmac"}
    event["audit_hmac"] = derive_adjudication_audit_hmac(
        KEY.encode(), task_id, index, prev, payload
    )
    return event


def _tagged_stream(
    n: int = 2, task_id: str = TASK_ID, tag_all: bool = True
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    prev: str | None = None
    for index in range(n):
        event = _event(index, task_id, prev)
        if not tag_all and index == 0:
            event["audit_hmac"] = None
        prev = event["audit_hmac"]
        events.append(event)
    return [
        {
            "task_id": task_id,
            "owner_id": "reviewer-a",
            "adjudications": events,
        }
    ]


def _mutated_stream(mutator: Any) -> list[dict[str, Any]]:
    stream = _tagged_stream(3)
    mutator(stream)
    return stream


def test_accepts_a_chained_tagged_stream() -> None:
    ok, issues, unaudited = validate_tasks(_tagged_stream(3), KEY.encode())

    assert ok, issues
    assert issues == []
    assert unaudited == 0


def test_accepts_unaudited_prefix_and_reports_its_count() -> None:
    ok, issues, unaudited = validate_tasks(_tagged_stream(2, tag_all=False), KEY.encode())

    assert ok, issues
    assert issues == []
    assert unaudited == 1


def test_accepts_tasks_without_adjudications() -> None:
    ok, issues, unaudited = validate_tasks(
        [{"task_id": "network-empty", "adjudications": []}], KEY.encode()
    )

    assert ok, issues
    assert unaudited == 0


def test_rejects_an_edited_decision() -> None:
    def mutate(stream: list[dict[str, Any]]) -> None:
        stream[0]["adjudications"][1]["decision"] = "included"

    ok, issues, _ = validate_tasks(_mutated_stream(mutate), KEY.encode())

    assert not ok
    assert any("audit_hmac mismatch" in issue for issue in issues)


def test_rejects_an_edited_reviewer_identity() -> None:
    def mutate(stream: list[dict[str, Any]]) -> None:
        stream[0]["adjudications"][0]["reviewer_id"] = "reviewer-b"

    ok, issues, _ = validate_tasks(_mutated_stream(mutate), KEY.encode())

    assert not ok
    assert any("reviewer-b" in issue for issue in issues)


def test_rejects_an_edited_decided_at() -> None:
    def mutate(stream: list[dict[str, Any]]) -> None:
        stream[0]["adjudications"][2]["decided_at"] = "2026-09-28T09:00:00+00:00"

    ok, issues, _ = validate_tasks(_mutated_stream(mutate), KEY.encode())

    assert not ok
    assert any("audit_hmac mismatch" in issue for issue in issues)


def test_rejects_an_edited_adjudication_id() -> None:
    def mutate(stream: list[dict[str, Any]]) -> None:
        stream[0]["adjudications"][0]["adjudication_id"] = "adjudication-f" + "0" * 63

    ok, issues, _ = validate_tasks(_mutated_stream(mutate), KEY.encode())

    assert not ok
    assert any("audit_hmac mismatch" in issue for issue in issues)


def test_rejects_a_forged_tag() -> None:
    def mutate(stream: list[dict[str, Any]]) -> None:
        stream[0]["adjudications"][1]["audit_hmac"] = "f" * 64

    ok, issues, _ = validate_tasks(_mutated_stream(mutate), KEY.encode())

    assert not ok
    assert any("audit_hmac mismatch" in issue for issue in issues)


def test_rejects_a_deleted_audited_event() -> None:
    def mutate(stream: list[dict[str, Any]]) -> None:
        del stream[0]["adjudications"][1]

    ok, issues, _ = validate_tasks(_mutated_stream(mutate), KEY.encode())

    assert not ok
    assert any("audit_hmac mismatch" in issue for issue in issues)


def test_rejects_reordered_events() -> None:
    def mutate(stream: list[dict[str, Any]]) -> None:
        events = stream[0]["adjudications"]
        events[1], events[2] = events[2], events[1]

    ok, issues, _ = validate_tasks(_mutated_stream(mutate), KEY.encode())

    assert not ok
    assert any("audit_hmac mismatch" in issue for issue in issues)


def test_rejects_a_stripped_tag_inside_the_audited_era() -> None:
    def mutate(stream: list[dict[str, Any]]) -> None:
        stream[0]["adjudications"][1]["audit_hmac"] = None

    ok, issues, unaudited = validate_tasks(_mutated_stream(mutate), KEY.encode())

    assert not ok
    assert any("audit_hmac mismatch" in issue for issue in issues)
    assert unaudited == 1


def test_rejects_duplicate_adjudication_ids() -> None:
    def mutate(stream: list[dict[str, Any]]) -> None:
        stream[0]["adjudications"][1]["adjudication_id"] = stream[0]["adjudications"][0][
            "adjudication_id"
        ]

    ok, issues, _ = validate_tasks(_mutated_stream(mutate), KEY.encode())

    assert not ok
    assert any("duplicate adjudication_id" in issue for issue in issues)


def test_rejects_everything_under_a_wrong_key() -> None:
    ok, issues, _ = validate_tasks(_tagged_stream(2), b"wrong-key")

    assert not ok
    assert len(issues) == 2


def test_rejects_a_non_string_tag() -> None:
    """A present-but-non-string tag is producer-impossible corruption; it must
    be a violation, never a silent ``unaudited`` downgrade."""

    def mutate(stream: list[dict[str, Any]]) -> None:
        stream[0]["adjudications"][1]["audit_hmac"] = 123

    ok, issues, _ = validate_tasks(_mutated_stream(mutate), KEY.encode())

    assert not ok
    assert any("audit_hmac must be a 64-character string" in issue for issue in issues)


def test_rejects_a_wrong_length_tag() -> None:
    def mutate(stream: list[dict[str, Any]]) -> None:
        stream[0]["adjudications"][2]["audit_hmac"] = "f" * 63

    ok, issues, _ = validate_tasks(_mutated_stream(mutate), KEY.encode())

    assert not ok
    assert any("audit_hmac must be a 64-character string" in issue for issue in issues)


def test_tail_deletion_is_outside_the_chain_detection_scope() -> None:
    """Honest boundary (dc2d01d review 🟠1): a self-contained chain has no
    successor whose ``prev`` link could mismatch, so deleting the LAST audited
    event is invisible to it. This test locks that truth so nobody mistakes
    exit 0 for ``nothing was truncated``; detecting tail truncation needs an
    external anchor (plan-bound full-stream tuple or counter file), which is
    a deferred decision in the handoff."""

    def mutate(stream: list[dict[str, Any]]) -> None:
        del stream[0]["adjudications"][2]

    ok, issues, unaudited = validate_tasks(_mutated_stream(mutate), KEY.encode())

    assert ok, issues
    assert issues == []
    assert unaudited == 0


def test_tail_tag_strip_is_reported_as_unaudited_not_violation() -> None:
    def mutate(stream: list[dict[str, Any]]) -> None:
        stream[0]["adjudications"][2]["audit_hmac"] = None

    ok, issues, unaudited = validate_tasks(_mutated_stream(mutate), KEY.encode())

    assert ok, issues
    assert issues == []
    assert unaudited == 1


def test_rejects_duplicate_task_ids_in_input() -> None:
    stream = _tagged_stream(2)
    stream.append(dict(stream[0]))

    ok, issues, _ = validate_tasks(stream, KEY.encode())

    assert not ok
    assert any("duplicate task_id" in issue for issue in issues)


def _seed_and_append(repo: NetworkTaskRepository | SqliteNetworkTaskRepository) -> None:
    repo.upsert(
        task_id=TASK_ID,
        owner_id="reviewer-a",
        query="消风散",
        analysis_type="formula",
        status="completed",
        progress=100,
        poll_count=2,
        result=None,
        created_at="2026-09-28T00:00:00+00:00",
    )
    event = NetworkTargetAdjudication(
        adjudication_id="adjudication-" + "b" * 64,
        lineage_row_id=ROW_ID,
        decision="included",
        # CJK on purpose: the acceptance recomputation must cross non-ASCII
        # bytes so an ensure_ascii drift between the two zero-shared
        # canonicalizations cannot hide behind a reason-less event.
        reason="人工复核",
        decided_at="2026-09-28T10:00:00+00:00",
        reviewer_id="reviewer-a",
    )
    updated = repo.append_adjudication(TASK_ID, "reviewer-a", event)
    assert updated is not None
    assert updated.adjudications[0].audit_hmac is not None


def _close_quietly(repo: object) -> None:
    close = getattr(repo, "close", None)
    if callable(close):
        close()


def _make_json_state(directory: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(AUDIT_KEY_ENV, KEY)
    state_path = directory / "network_tasks_state.json"
    state_path.write_text("[]\n", encoding="utf-8")
    repo = NetworkTaskRepository(state_path)
    try:
        _seed_and_append(repo)
    finally:
        _close_quietly(repo)
    return state_path


def _make_sqlite_state(directory: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(AUDIT_KEY_ENV, KEY)
    seed_path = directory / "network_tasks_state.json"
    seed_path.write_text("[]\n", encoding="utf-8")
    db_path = directory / "audit.sqlite3"
    repo = SqliteNetworkTaskRepository(db_path, seed_path=seed_path)
    try:
        _seed_and_append(repo)
    finally:
        _close_quietly(repo)
    return db_path


def test_cli_accepts_real_json_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_path = _make_json_state(tmp_path, monkeypatch)
    monkeypatch.setenv(AUDIT_KEY_ENV, KEY)

    assert main(["--state-json", str(state_path)]) == 0


def test_cli_accepts_real_sqlite_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = _make_sqlite_state(tmp_path, monkeypatch)
    monkeypatch.setenv(AUDIT_KEY_ENV, KEY)

    assert main(["--sqlite-db", str(db_path)]) == 0


def test_cli_rejects_tampered_real_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_path = _make_json_state(tmp_path, monkeypatch)
    records = json.loads(state_path.read_text(encoding="utf-8"))
    records[0]["adjudications"][0]["decision"] = "excluded"
    state_path.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    monkeypatch.setenv(AUDIT_KEY_ENV, KEY)

    assert main(["--state-json", str(state_path)]) == 1


def test_cli_fails_closed_without_key_or_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(AUDIT_KEY_ENV, raising=False)
    assert main(["--state-json", str(tmp_path / "missing.json")]) == 2

    monkeypatch.setenv(AUDIT_KEY_ENV, KEY)
    assert main([]) == 2


def test_cli_reports_missing_state_file_as_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(AUDIT_KEY_ENV, KEY)

    assert main(["--state-json", str(tmp_path / "missing.json")]) == 2
