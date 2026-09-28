"""Adjudication audit HMAC (writer consumption contract §6.2 deferred slice).

Server-private chained HMAC over the append-only adjudication stream: opt-in
via ``QIYAN_ADJUDICATION_AUDIT_KEY``, computed inside the repository critical
section, persisted on the event, never projected to any API surface. The
independent zero-shared validator script is cross-checked against this
derivation in ``test_validate_adjudication_audit_script.py``.
"""

import json
from datetime import date
from pathlib import Path
from typing import Literal

import pytest

from app.core.audit_hmac import (
    AUDIT_KEY_ENV,
    derive_adjudication_audit_hmac,
    load_audit_key,
)
from app.repositories.network_tasks import NetworkTaskRepository
from app.repositories.sqlite_network_tasks import SqliteNetworkTaskRepository
from app.schemas.network import (
    NetworkAnalysisResult,
    NetworkTargetAdjudication,
    NetworkTargetAdjudicationRecord,
    NetworkTargetLineage,
    NetworkTargetLineageRow,
    NetworkTaskRecord,
)
from app.services.network_adjudication import _adjudication_summary
from app.services.network_assembly import _adjudication_latest_snapshot

AUDIT_KEY = "audit-test-key"
TASK_ID = "network-audit-target"
OWNER_ID = "reviewer-a"
ROW_ID = "disease-" + "a" * 64
DISCLAIMER = "非诊断结论、需结合临床。"


@pytest.fixture(params=["json", "sqlite"], ids=["json", "sqlite"])
def backend(request: pytest.FixtureRequest) -> Literal["json", "sqlite"]:
    backend = request.param
    assert backend in ("json", "sqlite")
    return backend


@pytest.fixture(autouse=True)
def _hermetic_audit_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ambient audit key may leak in or out of a single test."""
    monkeypatch.delenv(AUDIT_KEY_ENV, raising=False)


def _open_repo(backend: Literal["json", "sqlite"], directory: Path, *, seed: bool = True):
    if backend == "json":
        state_path = directory / "network_tasks_state.json"
        if seed:
            state_path.write_text("[]\n", encoding="utf-8")
        return NetworkTaskRepository(state_path)
    seed_path = directory / "network_tasks_state.json"
    if seed:
        seed_path.write_text("[]\n", encoding="utf-8")
    return SqliteNetworkTaskRepository(directory / "audit.sqlite3", seed_path=seed_path)


def _close(repo: object) -> None:
    close = getattr(repo, "close", None)
    if callable(close):
        close()


def _seed(repo: object) -> None:
    repo.upsert(  # type: ignore[attr-defined]
        task_id=TASK_ID,
        owner_id=OWNER_ID,
        query="消风散",
        analysis_type="formula",
        status="completed",
        progress=100,
        poll_count=2,
        result=None,
        created_at="2026-09-28T00:00:00+00:00",
    )


def _event(
    adjudication_id: str,
    *,
    decision: Literal["included", "excluded"] = "included",
    decided_at: str = "2026-09-28T10:00:00+00:00",
) -> NetworkTargetAdjudication:
    return NetworkTargetAdjudication(
        adjudication_id=adjudication_id,
        lineage_row_id=ROW_ID,
        decision=decision,
        reason="人工复核",
        decided_at=decided_at,
        reviewer_id=OWNER_ID,
    )


def _audit_payload(event: NetworkTargetAdjudication) -> dict[str, object]:
    dump = event.model_dump(mode="json")
    return {key: value for key, value in dump.items() if key != "audit_hmac"}


def test_load_audit_key_env_semantics(monkeypatch: pytest.MonkeyPatch) -> None:
    assert load_audit_key() is None
    monkeypatch.setenv(AUDIT_KEY_ENV, "")
    assert load_audit_key() is None
    monkeypatch.setenv(AUDIT_KEY_ENV, "s3cret-key")
    assert load_audit_key() == b"s3cret-key"


def test_derivation_is_deterministic_keyed_and_input_sensitive() -> None:
    payload = {"adjudication_id": "adjudication-x", "reviewer_id": "reviewer-a"}
    base = derive_adjudication_audit_hmac(b"k1", TASK_ID, 0, None, payload)

    assert len(base) == 64
    assert set(base) <= set("0123456789abcdef")
    assert base == derive_adjudication_audit_hmac(b"k1", TASK_ID, 0, None, payload)
    assert base != derive_adjudication_audit_hmac(b"k2", TASK_ID, 0, None, payload)
    assert base != derive_adjudication_audit_hmac(b"k1", "network-other", 0, None, payload)
    assert base != derive_adjudication_audit_hmac(b"k1", TASK_ID, 1, None, payload)
    assert base != derive_adjudication_audit_hmac(b"k1", TASK_ID, 0, "0" * 64, payload)
    assert base != derive_adjudication_audit_hmac(
        b"k1", TASK_ID, 0, None, {**payload, "reviewer_id": "reviewer-b"}
    )


def test_append_without_key_keeps_events_untagged(
    backend: Literal["json", "sqlite"], tmp_path: Path
) -> None:
    repo = _open_repo(backend, tmp_path)
    try:
        _seed(repo)
        updated = repo.append_adjudication(TASK_ID, OWNER_ID, _event("adjudication-" + "b" * 64))
        assert updated is not None
        assert [event.audit_hmac for event in updated.adjudications] == [None]
    finally:
        _close(repo)


def test_append_with_key_persists_chained_tags(
    backend: Literal["json", "sqlite"], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(AUDIT_KEY_ENV, AUDIT_KEY)
    repo = _open_repo(backend, tmp_path)
    try:
        _seed(repo)
        first = _event("adjudication-" + "b" * 64)
        second = _event(
            "adjudication-" + "c" * 64,
            decision="excluded",
            decided_at="2026-09-28T11:00:00+00:00",
        )
        updated_first = repo.append_adjudication(TASK_ID, OWNER_ID, first)
        updated_second = repo.append_adjudication(TASK_ID, OWNER_ID, second)
        assert updated_first is not None and updated_second is not None
        first_tag = updated_first.adjudications[0].audit_hmac
        second_tag = updated_second.adjudications[1].audit_hmac

        assert first_tag is not None and len(first_tag) == 64
        assert second_tag is not None and len(second_tag) == 64
        assert first_tag != second_tag
        # The second tag chains from the first tag at full-stream index 1.
        assert second_tag == derive_adjudication_audit_hmac(
            AUDIT_KEY.encode(), TASK_ID, 1, first_tag, _audit_payload(second)
        )
    finally:
        _close(repo)


def test_tags_persist_across_repository_instances(
    backend: Literal["json", "sqlite"], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(AUDIT_KEY_ENV, AUDIT_KEY)
    repo = _open_repo(backend, tmp_path)
    _seed(repo)
    updated = repo.append_adjudication(TASK_ID, OWNER_ID, _event("adjudication-" + "b" * 64))
    assert updated is not None
    persisted_tag = updated.adjudications[0].audit_hmac
    _close(repo)

    reopened = _open_repo(backend, tmp_path, seed=False)
    try:
        record = reopened.get_owned(TASK_ID, OWNER_ID)  # type: ignore[attr-defined]
        assert record is not None
        assert record.adjudications[0].audit_hmac == persisted_tag
    finally:
        _close(reopened)


def test_tag_sequences_identical_across_backends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(AUDIT_KEY_ENV, AUDIT_KEY)
    tags_by_backend: dict[str, list[str | None]] = {}
    for backend in ("json", "sqlite"):
        directory = tmp_path / backend
        directory.mkdir()
        repo = _open_repo(backend, directory)  # type: ignore[arg-type]
        try:
            _seed(repo)
            repo.append_adjudication(TASK_ID, OWNER_ID, _event("adjudication-" + "b" * 64))
            updated = repo.append_adjudication(
                TASK_ID,
                OWNER_ID,
                _event(
                    "adjudication-" + "c" * 64,
                    decision="excluded",
                    decided_at="2026-09-28T11:00:00+00:00",
                ),
            )
            assert updated is not None
            tags_by_backend[backend] = [event.audit_hmac for event in updated.adjudications]
        finally:
            _close(repo)
    assert tags_by_backend["json"][0] is not None
    assert tags_by_backend["json"] == tags_by_backend["sqlite"]


def test_untagged_prefix_then_tagged_segment(
    backend: Literal["json", "sqlite"], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _open_repo(backend, tmp_path)
    try:
        _seed(repo)
        legacy = repo.append_adjudication(TASK_ID, OWNER_ID, _event("adjudication-" + "b" * 64))
        assert legacy is not None and legacy.adjudications[0].audit_hmac is None

        monkeypatch.setenv(AUDIT_KEY_ENV, AUDIT_KEY)
        tagged = repo.append_adjudication(TASK_ID, OWNER_ID, _event("adjudication-" + "c" * 64))
        assert tagged is not None
        # The segment starts here: prev is the untagged neighbour (null), and
        # sequence is the full-stream index including the unaudited prefix.
        assert tagged.adjudications[1].audit_hmac == derive_adjudication_audit_hmac(
            AUDIT_KEY.encode(), TASK_ID, 1, None, _audit_payload(tagged.adjudications[1])
        )
    finally:
        _close(repo)


def _lineage_result() -> NetworkAnalysisResult:
    row = NetworkTargetLineageRow(
        lineage_row_id=ROW_ID,
        raw_identifier="EFO_0000274",
        canonical_symbol="IL6",
        source_database="Open Targets Platform",
        query_date=date(2026, 7, 11),
        identifier_mapping="Ensembl target approvedSymbol",
        evidence_origin="disease_association",
    )
    return NetworkAnalysisResult(
        task_id=TASK_ID,
        query="消风散",
        analysis_type="formula",
        chains=[],
        disclaimer=DISCLAIMER,
        target_lineage=NetworkTargetLineage(
            disease_targets=[row], disease_target_count=1, disease_lineage_row_count=1
        ),
    )


def _record_with_adjudication(audit_hmac: str | None) -> NetworkTaskRecord:
    event = _event("adjudication-" + "b" * 64)
    return NetworkTaskRecord(
        task_id=TASK_ID,
        owner_id=OWNER_ID,
        query="消风散",
        analysis_type="formula",
        status="completed",
        progress=100,
        poll_count=2,
        result=_lineage_result(),
        adjudications=[event.model_copy(update={"audit_hmac": audit_hmac})],
        created_at="2026-09-28T00:00:00+00:00",
    )


def test_plan_snapshot_projection_ignores_audit_hmac() -> None:
    untagged = _adjudication_latest_snapshot(_record_with_adjudication(None))
    tagged = _adjudication_latest_snapshot(_record_with_adjudication("c" * 64))

    assert untagged == tagged
    assert tagged != []


def test_public_projections_never_carry_audit_hmac() -> None:
    record = _record_with_adjudication("c" * 64)

    assert "audit_hmac" not in NetworkTargetAdjudicationRecord.model_fields
    summary_dump = json.dumps(_adjudication_summary(record).model_dump(mode="json"))
    assert "audit_hmac" not in summary_dump
    snapshot_dump = json.dumps(_adjudication_latest_snapshot(record))
    assert "audit_hmac" not in snapshot_dump
