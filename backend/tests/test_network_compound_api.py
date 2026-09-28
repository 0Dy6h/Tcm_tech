import hashlib
import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repositories.runtime_storage import (
    clear_network_task_repository_cache,
    get_network_task_repository,
)
from app.schemas.network import NetworkCompoundTargetVerifyMetadata
from app.services.network_tasks import create_verified_compound_network_analysis_task

OPEN_TARGETS_FIXTURE = (
    Path(__file__).parent / "data" / "open_targets_graphql_associations_25_06.json"
)
CHEMBL_FIXTURE = Path(__file__).parent / "data" / "chembl_known_activities_34.json"

DISEASE_METADATA = {
    "source_profile": "open_targets_association_v1",
    "disease": "atopic_dermatitis",
    "phenotype": "特应性皮炎伴 2 型炎症与皮肤屏障异常",
    "species": "Homo sapiens",
    "source_database": "Open Targets Platform",
    "database_version": "25.06",
    "source_query_id": "EFO_0000274",
    "source_query_label": "atopic eczema",
    "source_query_parameters": {"datatype": "overall"},
    "query_date": "2026-07-11",
    "retrieved_at": "2026-07-11T08:30:00Z",
    "score_name": "association_score",
    "applied_threshold": 0.6,
    "threshold_operator": "gte",
    "identifier_mapping": "Ensembl target approvedSymbol",
    "identifier_mapping_version": "25.06",
    "usage_license_note": "Open Targets Platform data; see platform terms.",
}

COMPOUND_METADATA = {
    "source_profile": "chembl_known_activity_v1",
    "compound_id": "CHEMBL1201587",
    "compound_label": "Quercetin",
    "species": "Homo sapiens",
    "source_database": "ChEMBL",
    "database_version": "34",
    "source_query_id": "CHEMBL1201587",
    "source_query_label": "Quercetin",
    "source_query_parameters": {
        "assay_organism": "Homo sapiens",
        "standard_type": "IC50",
        "pchembl_value_min": 6.0,
    },
    "query_date": "2026-07-11",
    "retrieved_at": "2026-07-11T08:30:00Z",
    "score_name": "pchembl_value",
    "applied_threshold": 6.0,
    "threshold_operator": "gte",
    "identifier_mapping": "ChEMBL target component gene symbol",
    "identifier_mapping_version": "34",
    "usage_license_note": "ChEMBL data; see database terms.",
}


@pytest.fixture(autouse=True)
def _isolate_network_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clear_network_task_repository_cache()
    monkeypatch.setenv(
        "NETWORK_TASKS_RUNTIME_STATE_PATH", str(tmp_path / "network_tasks_state.json")
    )
    monkeypatch.setenv("NETWORK_RAW_ARTIFACT_DIR", str(tmp_path / "network_raw_artifacts"))
    disease_manifest = tmp_path / "trusted-open-targets-manifest.json"
    disease_manifest.write_text(
        json.dumps(
            {
                "artifacts": {
                    hashlib.sha256(OPEN_TARGETS_FIXTURE.read_bytes()).hexdigest(): DISEASE_METADATA
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    compound_manifest = tmp_path / "trusted-chembl-manifest.json"
    compound_manifest.write_text(
        json.dumps(
            {
                "artifacts": {
                    hashlib.sha256(CHEMBL_FIXTURE.read_bytes()).hexdigest(): COMPOUND_METADATA
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NETWORK_OPEN_TARGETS_MANIFEST_PATH", str(disease_manifest))
    monkeypatch.setenv("NETWORK_CHEMBL_MANIFEST_PATH", str(compound_manifest))
    yield
    clear_network_task_repository_cache()


def _create_verified_disease_task(
    client: TestClient,
    headers: dict[str, str] | None = None,
) -> str:
    response = client.post(
        "/api/network/disease-import/verify",
        data={
            "query": "消风散",
            "analysis_type": "formula",
            "evidence_policy": "direct_human_first",
            "metadata": json.dumps(DISEASE_METADATA, ensure_ascii=False),
        },
        files={
            "file": (
                OPEN_TARGETS_FIXTURE.name,
                OPEN_TARGETS_FIXTURE.read_bytes(),
                "application/json",
            )
        },
        headers=headers,
    )
    assert response.status_code == 202
    return response.json()["task_id"]


def test_verify_compound_import_creates_a_new_task_without_mutating_verified_disease_task() -> None:
    client = TestClient(app)
    source_task_id = _create_verified_disease_task(client)
    source_before = get_network_task_repository().get_owned(source_task_id, "local-preview")
    assert source_before is not None
    assert source_before.compound_target_import is None

    response = client.post(
        "/api/network/compound-import/verify",
        data={
            "source_task_id": source_task_id,
            "metadata": json.dumps(COMPOUND_METADATA, ensure_ascii=False),
        },
        files={
            "file": (
                CHEMBL_FIXTURE.name,
                CHEMBL_FIXTURE.read_bytes(),
                "application/json",
            )
        },
    )

    assert response.status_code == 202
    derived_task_id = response.json()["task_id"]
    assert derived_task_id != source_task_id
    source_after = get_network_task_repository().get_owned(source_task_id, "local-preview")
    derived = get_network_task_repository().get_owned(derived_task_id, "local-preview")
    assert source_after == source_before
    assert derived is not None
    assert derived.source_task_id == source_task_id
    assert derived.research_protocol == source_before.research_protocol
    assert derived.disease_target_import == source_before.disease_target_import
    assert derived.compound_target_import is not None
    assert derived.compound_target_import.provenance_verification_status == (
        "server_verified_raw_artifact"
    )
    assert (
        derived.compound_target_import.source_artifact_sha256
        == hashlib.sha256(CHEMBL_FIXTURE.read_bytes()).hexdigest()
    )

    assert client.get(f"/api/network/result/{derived_task_id}").json()["status"] == "running"
    completed = client.get(f"/api/network/result/{derived_task_id}")
    assert completed.status_code == 200
    result = completed.json()["result"]
    assert result["source_task_id"] == source_task_id
    assert result["chains"] == []
    assert result["enrichment"] is None
    assert any(
        "导入靶点尚未构建可复算的成分-靶点-通路网络闭环" in warning
        for warning in result["warnings"]
    )
    lineage = result["target_lineage"]
    assert lineage["compound_import_provenance"]["source_profile"] == "chembl_known_activity_v1"
    assert lineage["compound_import_provenance"]["compound_id"] == "CHEMBL1201587"
    assert {row["database_version"] for row in lineage["compound_targets"]} == {"34"}
    assert {row["source_score"] for row in lineage["compound_targets"]} == {6.1, 6.4}
    assert {row["canonical_symbol"] for row in lineage["intersection_targets"]} == {"EGFR", "IL6"}
    assert result["readiness"]["formal_network_ready"] is False
    assert any(
        "导入靶点尚未构建可复算的成分-靶点-通路网络闭环" in reason
        for reason in result["readiness"]["blocking_reasons"]
    )


def test_verify_compound_import_retries_task_id_collision_without_mutating_existing_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(app)
    source_task_id = _create_verified_disease_task(client)
    repo = get_network_task_repository()
    collision_hex = "a" * 32
    unique_hex = "b" * 32
    collision_task_id = f"network-{collision_hex}"
    collision_before = repo.upsert(
        task_id=collision_task_id,
        owner_id="reviewer-b",
        query="do-not-touch",
        analysis_type="herb",
        status="failed",
        progress=100,
        poll_count=7,
        result=None,
        error="existing task",
        created_at="2026-07-15T00:00:00+00:00",
    )
    generated_ids = iter([SimpleNamespace(hex=collision_hex), SimpleNamespace(hex=unique_hex)])
    monkeypatch.setattr("app.services.network.uuid4", lambda: next(generated_ids))

    response = client.post(
        "/api/network/compound-import/verify",
        data={
            "source_task_id": source_task_id,
            "metadata": json.dumps(COMPOUND_METADATA, ensure_ascii=False),
        },
        files={
            "file": (
                CHEMBL_FIXTURE.name,
                CHEMBL_FIXTURE.read_bytes(),
                "application/json",
            )
        },
    )

    assert response.status_code == 202
    assert response.json()["task_id"] == f"network-{unique_hex}"
    assert repo.get(collision_task_id) == collision_before


@pytest.mark.parametrize(
    "forbidden_field",
    ["records", "source_artifact_sha256", "provenance_verification_status", "readiness"],
)
def test_verify_compound_import_rejects_client_controlled_derived_metadata(
    forbidden_field: str,
) -> None:
    client = TestClient(app)
    source_task_id = _create_verified_disease_task(client)
    metadata = {**COMPOUND_METADATA, forbidden_field: "client-controlled"}

    response = client.post(
        "/api/network/compound-import/verify",
        data={
            "source_task_id": source_task_id,
            "metadata": json.dumps(metadata, ensure_ascii=False),
        },
        files={
            "file": (
                CHEMBL_FIXTURE.name,
                CHEMBL_FIXTURE.read_bytes(),
                "application/json",
            )
        },
    )

    assert response.status_code == 422
    assert [record.task_id for record in get_network_task_repository().read_all()] == [
        source_task_id
    ]


def test_verify_compound_import_rejects_extra_top_level_multipart_fields() -> None:
    client = TestClient(app)
    source_task_id = _create_verified_disease_task(client)

    response = client.post(
        "/api/network/compound-import/verify",
        data={
            "source_task_id": source_task_id,
            "metadata": json.dumps(COMPOUND_METADATA, ensure_ascii=False),
            "source_artifact_sha256": "client-controlled",
        },
        files={
            "file": (
                CHEMBL_FIXTURE.name,
                CHEMBL_FIXTURE.read_bytes(),
                "application/json",
            )
        },
    )

    assert response.status_code == 422
    assert [record.task_id for record in get_network_task_repository().read_all()] == [
        source_task_id
    ]


def test_verify_compound_import_rejects_duplicate_multipart_fields() -> None:
    client = TestClient(app)
    source_task_id = _create_verified_disease_task(client)

    response = client.post(
        "/api/network/compound-import/verify",
        files=[
            ("source_task_id", (None, source_task_id)),
            ("source_task_id", (None, source_task_id)),
            ("metadata", (None, json.dumps(COMPOUND_METADATA, ensure_ascii=False))),
            (
                "file",
                (
                    CHEMBL_FIXTURE.name,
                    CHEMBL_FIXTURE.read_bytes(),
                    "application/json",
                ),
            ),
        ],
    )

    assert response.status_code == 422
    assert [record.task_id for record in get_network_task_repository().read_all()] == [
        source_task_id
    ]


def test_verify_compound_import_rejects_invalid_content_length_without_server_error() -> None:
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/network/compound-import/verify",
        content=b"not-a-valid-multipart-body",
        headers={
            "content-type": "multipart/form-data; boundary=qiyan",
            "content-length": "bogus",
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid Content-Length"}
    assert get_network_task_repository().read_all() == []


def test_verify_compound_import_rejects_oversized_artifact_before_persistence() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/network/compound-import/verify",
        data={
            "source_task_id": "network-" + "a" * 32,
            "metadata": json.dumps(COMPOUND_METADATA, ensure_ascii=False),
        },
        files={
            "file": (
                "too-large.json",
                b"x" * (5 * 1024 * 1024 + 1),
                "application/json",
            )
        },
    )

    assert response.status_code == 413
    assert get_network_task_repository().read_all() == []
    assert list(Path(os.environ["NETWORK_RAW_ARTIFACT_DIR"]).glob("*")) == []


def test_verify_compound_import_rejects_chunked_transfer_before_multipart_parse() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/network/compound-import/verify",
        headers={"Transfer-Encoding": "chunked"},
        data={
            "source_task_id": "network-" + "a" * 32,
            "metadata": json.dumps(COMPOUND_METADATA, ensure_ascii=False),
        },
        files={
            "file": (
                CHEMBL_FIXTURE.name,
                CHEMBL_FIXTURE.read_bytes(),
                "application/json",
            )
        },
    )

    assert response.status_code == 411
    assert get_network_task_repository().read_all() == []


def test_verify_compound_import_rejects_unknown_source_task_without_persisting_artifact() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/network/compound-import/verify",
        data={
            "source_task_id": "network-unknown",
            "metadata": json.dumps(COMPOUND_METADATA, ensure_ascii=False),
        },
        files={
            "file": (
                CHEMBL_FIXTURE.name,
                CHEMBL_FIXTURE.read_bytes(),
                "application/json",
            )
        },
    )

    assert response.status_code == 404
    assert get_network_task_repository().read_all() == []


def test_verify_compound_import_rejects_tampered_raw_bytes_without_creating_child_task() -> None:
    client = TestClient(app)
    source_task_id = _create_verified_disease_task(client)

    response = client.post(
        "/api/network/compound-import/verify",
        data={
            "source_task_id": source_task_id,
            "metadata": json.dumps(COMPOUND_METADATA, ensure_ascii=False),
        },
        files={
            "file": (
                CHEMBL_FIXTURE.name,
                CHEMBL_FIXTURE.read_bytes() + b"\n",
                "application/json",
            )
        },
    )

    assert response.status_code == 422
    assert [record.task_id for record in get_network_task_repository().read_all()] == [
        source_task_id
    ]


def test_compound_import_source_task_lookup_is_owner_scoped() -> None:
    client = TestClient(app)
    source_task_id = _create_verified_disease_task(client)

    with pytest.raises(LookupError, match="not found"):
        create_verified_compound_network_analysis_task(
            source_task_id=source_task_id,
            reviewer_id="reviewer-b",
            metadata=NetworkCompoundTargetVerifyMetadata.model_validate(COMPOUND_METADATA),
            raw_bytes=CHEMBL_FIXTURE.read_bytes(),
            source_artifact_filename=CHEMBL_FIXTURE.name,
            source_artifact_media_type="application/json",
        )

    assert [record.task_id for record in get_network_task_repository().read_all()] == [
        source_task_id
    ]


def test_protected_compound_import_hides_a_foreign_source_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_access_tokens = os.environ.get("QIYAN_ACCESS_TOKENS")
    monkeypatch.setenv("QIYAN_ACCESS_TOKENS", "alpha")
    main_module = importlib.import_module("app.main")
    importlib.reload(main_module)
    reviewer_a_headers = {
        "X-Access-Token": "alpha",
        "X-Qiyan-Reviewer": "reviewer-a",
    }
    reviewer_b_headers = {
        "X-Access-Token": "alpha",
        "X-Qiyan-Reviewer": "reviewer-b",
    }

    try:
        client = TestClient(main_module.app)
        source_task_id = _create_verified_disease_task(client, reviewer_a_headers)
        artifact_dir = Path(os.environ["NETWORK_RAW_ARTIFACT_DIR"])
        artifacts_before = {path.name for path in artifact_dir.glob("*")}

        response = client.post(
            "/api/network/compound-import/verify",
            data={
                "source_task_id": source_task_id,
                "metadata": json.dumps(COMPOUND_METADATA, ensure_ascii=False),
            },
            files={
                "file": (
                    CHEMBL_FIXTURE.name,
                    CHEMBL_FIXTURE.read_bytes(),
                    "application/json",
                )
            },
            headers=reviewer_b_headers,
        )

        assert response.status_code == 404
        assert response.json() == {"detail": "Network analysis task not found"}
        assert [record.task_id for record in get_network_task_repository().read_all()] == [
            source_task_id
        ]
        assert {path.name for path in artifact_dir.glob("*")} == artifacts_before
    finally:
        if original_access_tokens is None:
            monkeypatch.delenv("QIYAN_ACCESS_TOKENS", raising=False)
        else:
            monkeypatch.setenv("QIYAN_ACCESS_TOKENS", original_access_tokens)
        importlib.reload(main_module)


def test_compound_child_cannot_be_used_as_another_compound_parent() -> None:
    client = TestClient(app)
    parent_task_id = _create_verified_disease_task(client)
    child_response = client.post(
        "/api/network/compound-import/verify",
        data={
            "source_task_id": parent_task_id,
            "metadata": json.dumps(COMPOUND_METADATA, ensure_ascii=False),
        },
        files={
            "file": (
                CHEMBL_FIXTURE.name,
                CHEMBL_FIXTURE.read_bytes(),
                "application/json",
            )
        },
    )
    assert child_response.status_code == 202
    child_task_id = child_response.json()["task_id"]

    with pytest.raises(ValueError, match="already a compound target child"):
        create_verified_compound_network_analysis_task(
            source_task_id=child_task_id,
            reviewer_id="local-preview",
            metadata=NetworkCompoundTargetVerifyMetadata.model_validate(COMPOUND_METADATA),
            raw_bytes=CHEMBL_FIXTURE.read_bytes(),
            source_artifact_filename=CHEMBL_FIXTURE.name,
            source_artifact_media_type="application/json",
        )

    assert [record.task_id for record in get_network_task_repository().read_all()] == [
        parent_task_id,
        child_task_id,
    ]
