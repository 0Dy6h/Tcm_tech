import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.repositories.network_cache import NetworkCacheRepository, build_network_cache_key
from app.repositories.runtime_storage import get_network_task_repository
from app.services.network_connectors import UniProtConnector

RESEARCH_PROTOCOL = {
    "disease": "atopic_dermatitis",
    "phenotype": "特应性皮炎伴 2 型炎症与皮肤屏障异常",
    "species": "Homo sapiens",
    "evidence_policy": "direct_human_first",
    "query_date": "2026-07-11",
}

DISEASE_TARGET_IMPORT = {
    "source_profile": "open_targets_association_v1",
    "disease": "atopic_dermatitis",
    "phenotype": "特应性皮炎伴 2 型炎症与皮肤屏障异常",
    "species": "Homo sapiens",
    "source_database": "Open Targets Platform",
    "database_version": "25.06",
    "source_query_id": "EFO_0000274",
    "source_query_label": "atopic eczema",
    "source_query_parameters": {
        "datatypes": ["genetic_association", "literature"],
        "score_aggregation": "harmonic_sum",
    },
    "query_date": "2026-07-11",
    "retrieved_at": "2026-07-11T08:30:00Z",
    "score_name": "association_score",
    "applied_threshold": 0.6,
    "threshold_operator": "gte",
    "identifier_mapping": "Ensembl target approvedSymbol",
    "identifier_mapping_version": "Open Targets Platform 25.06",
    "records": [
        {
            "raw_identifier": "ENSG00000136244",
            "canonical_symbol": "IL6",
            "source_record_id": "EFO_0000274:ENSG00000136244:genetic_association",
            "source_score": 0.91,
        },
        {
            "raw_identifier": "ENSG00000136244",
            "canonical_symbol": "IL6",
            "source_record_id": "EFO_0000274:ENSG00000136244:literature",
            "source_score": 0.73,
        },
        {
            "raw_identifier": "ENSG00000143631",
            "canonical_symbol": "FLG",
            "source_record_id": "EFO_0000274:ENSG00000143631:genetic_association",
            "source_score": 0.88,
        },
    ],
}

VERIFIED_IMPORT_METADATA = {
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
OPEN_TARGETS_FIXTURE = (
    Path(__file__).parent / "data" / "open_targets_graphql_associations_25_06.json"
)


@pytest.fixture(autouse=True)
def _isolate_network_tasks_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "NETWORK_TASKS_RUNTIME_STATE_PATH", str(tmp_path / "network_tasks_state.json")
    )
    monkeypatch.setenv("NETWORK_RAW_ARTIFACT_DIR", str(tmp_path / "network_raw_artifacts"))
    manifest_path = tmp_path / "trusted-open-targets-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "artifacts": {
                    hashlib.sha256(
                        OPEN_TARGETS_FIXTURE.read_bytes()
                    ).hexdigest(): VERIFIED_IMPORT_METADATA
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NETWORK_OPEN_TARGETS_MANIFEST_PATH", str(manifest_path))


def test_network_analyze_endpoint_creates_task():
    client = TestClient(app)

    response = client.post(
        "/api/network/analyze",
        json={
            "query": "消风散",
            "analysis_type": "formula",
            "research_protocol": RESEARCH_PROTOCOL,
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["progress"] == 0
    assert payload["data_mode"] == "mock"
    assert payload["task_id"].startswith("network-")


def test_network_analyze_endpoint_requires_a_research_protocol():
    client = TestClient(app)

    response = client.post(
        "/api/network/analyze",
        json={"query": "消风散", "analysis_type": "formula"},
    )

    assert response.status_code == 422


def test_network_analyze_rejects_overlong_query() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/network/analyze",
        json={
            "query": "超" * 101,
            "analysis_type": "formula",
            "research_protocol": RESEARCH_PROTOCOL,
        },
    )

    assert response.status_code == 422


def test_network_analyze_rejects_future_query_date() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/network/analyze",
        json={
            "query": "消风散",
            "analysis_type": "formula",
            "research_protocol": {**RESEARCH_PROTOCOL, "query_date": "2099-01-01"},
        },
    )

    assert response.status_code == 422


def test_verify_disease_import_creates_owner_scoped_task_from_raw_artifact() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/network/disease-import/verify",
        data={
            "query": "消风散",
            "analysis_type": "formula",
            "evidence_policy": "direct_human_first",
            "metadata": json.dumps(VERIFIED_IMPORT_METADATA, ensure_ascii=False),
        },
        files={
            "file": (
                OPEN_TARGETS_FIXTURE.name,
                OPEN_TARGETS_FIXTURE.read_bytes(),
                "application/x-ndjson",
            )
        },
    )

    assert response.status_code == 202
    task_id = response.json()["task_id"]
    client.get(f"/api/network/result/{task_id}")
    completed = client.get(f"/api/network/result/{task_id}").json()["result"]
    provenance = completed["target_lineage"]["disease_import_provenance"]
    assert provenance["provenance_verification_status"] == "server_verified_raw_artifact"
    assert len(provenance["source_artifact_sha256"]) == 64
    assert provenance["source_artifact_filename"] == OPEN_TARGETS_FIXTURE.name
    assert provenance["usage_license_note"].startswith("Open Targets Platform")
    assert completed["readiness"]["formal_network_ready"] is False
    stored_artifact = (
        Path(os.environ["NETWORK_RAW_ARTIFACT_DIR"])
        / f"{provenance['source_artifact_sha256']}.json"
    )
    assert stored_artifact.read_bytes() == OPEN_TARGETS_FIXTURE.read_bytes()


def test_verify_disease_import_retries_task_id_collision_without_mutating_existing_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(app)
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
        "/api/network/disease-import/verify",
        data={
            "query": "消风散",
            "analysis_type": "formula",
            "evidence_policy": "direct_human_first",
            "metadata": json.dumps(VERIFIED_IMPORT_METADATA, ensure_ascii=False),
        },
        files={
            "file": (
                OPEN_TARGETS_FIXTURE.name,
                OPEN_TARGETS_FIXTURE.read_bytes(),
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
def test_verify_disease_import_rejects_client_controlled_derived_fields(
    forbidden_field: str,
) -> None:
    client = TestClient(app)
    metadata = {**VERIFIED_IMPORT_METADATA, forbidden_field: []}

    response = client.post(
        "/api/network/disease-import/verify",
        data={
            "query": "消风散",
            "analysis_type": "formula",
            "evidence_policy": "direct_human_first",
            "metadata": json.dumps(metadata, ensure_ascii=False),
        },
        files={
            "file": (
                OPEN_TARGETS_FIXTURE.name,
                OPEN_TARGETS_FIXTURE.read_bytes(),
                "application/x-ndjson",
            )
        },
    )

    assert response.status_code == 422
    assert get_network_task_repository().read_all() == []


@pytest.mark.parametrize(
    "forbidden_field",
    ["records", "source_artifact_sha256", "provenance_verification_status", "readiness"],
)
def test_verify_disease_import_rejects_extra_top_level_multipart_fields(
    forbidden_field: str,
) -> None:
    client = TestClient(app)

    response = client.post(
        "/api/network/disease-import/verify",
        data={
            "query": "消风散",
            "analysis_type": "formula",
            "evidence_policy": "direct_human_first",
            "metadata": json.dumps(VERIFIED_IMPORT_METADATA, ensure_ascii=False),
            forbidden_field: "client-controlled",
        },
        files={
            "file": (
                OPEN_TARGETS_FIXTURE.name,
                OPEN_TARGETS_FIXTURE.read_bytes(),
                "application/json",
            )
        },
    )

    assert response.status_code == 422
    assert get_network_task_repository().read_all() == []


def test_verify_disease_import_rejects_duplicate_multipart_fields() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/network/disease-import/verify",
        files=[
            ("query", (None, "消风散")),
            ("query", (None, "消风散")),
            ("analysis_type", (None, "formula")),
            ("evidence_policy", (None, "direct_human_first")),
            ("metadata", (None, json.dumps(VERIFIED_IMPORT_METADATA, ensure_ascii=False))),
            (
                "file",
                (
                    OPEN_TARGETS_FIXTURE.name,
                    OPEN_TARGETS_FIXTURE.read_bytes(),
                    "application/json",
                ),
            ),
        ],
    )

    assert response.status_code == 422
    assert get_network_task_repository().read_all() == []


@pytest.mark.parametrize(
    ("metadata_updates", "raw_bytes"),
    [
        ({"database_version": "25.07"}, OPEN_TARGETS_FIXTURE.read_bytes()),
        ({}, b"{tampered"),
        ({}, OPEN_TARGETS_FIXTURE.read_bytes() + b"\n"),
        ({"applied_threshold": 0.8}, OPEN_TARGETS_FIXTURE.read_bytes()),
    ],
)
def test_verify_disease_import_fails_closed_on_artifact_mismatch(
    metadata_updates: dict[str, object], raw_bytes: bytes
) -> None:
    client = TestClient(app)

    response = client.post(
        "/api/network/disease-import/verify",
        data={
            "query": "消风散",
            "analysis_type": "formula",
            "evidence_policy": "direct_human_first",
            "metadata": json.dumps(
                {**VERIFIED_IMPORT_METADATA, **metadata_updates}, ensure_ascii=False
            ),
        },
        files={"file": (OPEN_TARGETS_FIXTURE.name, raw_bytes, "application/x-ndjson")},
    )

    assert response.status_code == 422
    assert get_network_task_repository().read_all() == []


def test_verify_disease_import_rejects_oversized_artifact_before_persistence() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/network/disease-import/verify",
        data={
            "query": "消风散",
            "analysis_type": "formula",
            "evidence_policy": "direct_human_first",
            "metadata": json.dumps(VERIFIED_IMPORT_METADATA, ensure_ascii=False),
        },
        files={"file": ("too-large.json", b"x" * (5 * 1024 * 1024 + 1), "application/json")},
    )

    assert response.status_code == 413
    assert get_network_task_repository().read_all() == []
    assert list(Path(os.environ["NETWORK_RAW_ARTIFACT_DIR"]).glob("*")) == []


def test_verify_disease_import_rejects_chunked_transfer_before_multipart_parse() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/network/disease-import/verify",
        headers={"Transfer-Encoding": "chunked"},
        data={
            "query": "消风散",
            "analysis_type": "formula",
            "evidence_policy": "direct_human_first",
            "metadata": json.dumps(VERIFIED_IMPORT_METADATA, ensure_ascii=False),
        },
        files={
            "file": (
                OPEN_TARGETS_FIXTURE.name,
                OPEN_TARGETS_FIXTURE.read_bytes(),
                "application/json",
            )
        },
    )

    assert response.status_code == 411
    assert get_network_task_repository().read_all() == []


def test_network_task_imports_disease_source_rows_and_recomputes_intersection():
    client = TestClient(app)

    create_response = client.post(
        "/api/network/analyze",
        json={
            "query": "消风散",
            "analysis_type": "formula",
            "research_protocol": RESEARCH_PROTOCOL,
            "disease_target_import": DISEASE_TARGET_IMPORT,
        },
    )
    assert create_response.status_code == 202
    task_id = create_response.json()["task_id"]

    assert client.get(f"/api/network/result/{task_id}").json()["status"] == "running"
    completed = client.get(f"/api/network/result/{task_id}")

    assert completed.status_code == 200
    lineage = completed.json()["result"]["target_lineage"]
    provenance = lineage["disease_import_provenance"]
    assert provenance["provenance_verification_status"] == "unverified_client_import"
    assert len(provenance["import_payload_sha256"]) == 64
    assert provenance["source_query_id"] == "EFO_0000274"
    assert provenance["record_count"] == 3
    assert lineage["observation_unit"] == "mixed"
    assert lineage["disease_observation_unit"] == "source_record"
    assert lineage["compound_observation_unit"] == "source_record"
    assert lineage["intersection_observation_unit"] == "canonical_symbol_derivation"
    assert lineage["disease_target_count"] == 2
    assert lineage["disease_lineage_row_count"] == 3
    assert [row["source_record_ids"][0] for row in lineage["disease_targets"]] == [
        "EFO_0000274:ENSG00000136244:genetic_association",
        "EFO_0000274:ENSG00000136244:literature",
        "EFO_0000274:ENSG00000143631:genetic_association",
    ]
    assert len({row["lineage_row_id"] for row in lineage["disease_targets"]}) == 3
    assert lineage["intersection_target_count"] == 1
    assert lineage["intersection_lineage_row_count"] == 1
    assert {row["canonical_symbol"] for row in lineage["intersection_targets"]} == {"IL6"}
    intersection = lineage["intersection_targets"][0]
    assert intersection["derivation"] == "canonical_symbol_exact_match_v1"
    assert set(intersection["disease_lineage_row_ids"]) == {
        row["lineage_row_id"]
        for row in lineage["disease_targets"]
        if row["canonical_symbol"] == "IL6"
    }
    assert set(intersection["compound_lineage_row_ids"]) == {
        row["lineage_row_id"]
        for row in lineage["compound_targets"]
        if row["canonical_symbol"] == "IL6"
    }
    assert all(row["adjudication_status"] == "pending" for row in lineage["disease_targets"])
    assert all(row["decision"] == "unreviewed" for row in lineage["disease_targets"])
    assert intersection["automatic_status"] == "derived"
    assert intersection["adjudication_status"] == "pending"
    assert intersection["decision"] == "unreviewed"
    blockers = completed.json()["result"]["readiness"]["blocking_reasons"]
    assert any("客户端导入" in blocker and "未验证" in blocker for blocker in blockers)
    assert any("派生交集" in blocker and "人工判定" in blocker for blocker in blockers)


def test_network_task_preserves_a_frozen_zero_hit_disease_import():
    client = TestClient(app)
    zero_hit_import = {**DISEASE_TARGET_IMPORT, "records": []}

    create_response = client.post(
        "/api/network/analyze",
        json={
            "query": "消风散",
            "analysis_type": "formula",
            "research_protocol": RESEARCH_PROTOCOL,
            "disease_target_import": zero_hit_import,
        },
    )
    assert create_response.status_code == 202
    task_id = create_response.json()["task_id"]
    client.get(f"/api/network/result/{task_id}")
    completed = client.get(f"/api/network/result/{task_id}").json()["result"]

    lineage = completed["target_lineage"]
    assert lineage["disease_import_provenance"]["record_count"] == 0
    assert lineage["disease_targets"] == []
    assert lineage["intersection_targets"] == []
    assert any("零命中" in warning for warning in lineage["warnings"])
    assert any("零命中" in blocker for blocker in completed["readiness"]["blocking_reasons"])


@pytest.mark.parametrize(
    "mutation",
    [
        "server_provenance",
        "row_adjudication",
        "declared_intersection",
        "protocol_mismatch",
        "below_threshold",
    ],
)
def test_network_analyze_rejects_untrusted_or_inconsistent_disease_imports(
    mutation: str,
) -> None:
    client = TestClient(app)
    request_payload = {
        "query": "消风散",
        "analysis_type": "formula",
        "research_protocol": deepcopy(RESEARCH_PROTOCOL),
        "disease_target_import": deepcopy(DISEASE_TARGET_IMPORT),
    }
    imported = request_payload["disease_target_import"]
    assert isinstance(imported, dict)
    if mutation == "server_provenance":
        imported["provenance_verification_status"] = "verified"
    elif mutation == "row_adjudication":
        imported["records"][0]["adjudication_status"] = "accepted"
    elif mutation == "declared_intersection":
        request_payload["intersection_targets"] = [{"canonical_symbol": "IL6"}]
    elif mutation == "protocol_mismatch":
        imported["phenotype"] = "特应性皮炎伴瘙痒"
    elif mutation == "below_threshold":
        imported["records"][0]["source_score"] = 0.1

    response = client.post("/api/network/analyze", json=request_payload)

    assert response.status_code == 422
    assert get_network_task_repository().read_all() == []


def test_network_result_endpoint_returns_progress_then_completed_result():
    client = TestClient(app)

    create_response = client.post(
        "/api/network/analyze",
        json={
            "query": "黄芪",
            "analysis_type": "herb",
            "research_protocol": RESEARCH_PROTOCOL,
        },
    )
    assert create_response.status_code == 202
    task_id = create_response.json()["task_id"]

    first_poll = client.get(f"/api/network/result/{task_id}")
    assert first_poll.status_code == 200
    first_payload = first_poll.json()
    assert first_payload["status"] == "running"
    assert first_payload["progress"] == 60
    assert first_payload["data_mode"] == "mock"
    assert first_payload["result"] is None

    second_poll = client.get(f"/api/network/result/{task_id}")
    assert second_poll.status_code == 200
    second_payload = second_poll.json()
    assert second_payload["status"] == "completed"
    assert second_payload["progress"] == 100
    assert second_payload["data_mode"] == "mock"
    assert second_payload["error"] is None
    assert second_payload["warnings"] == []
    assert second_payload["result"] is not None
    assert second_payload["result"]["data_mode"] == "mock"
    assert second_payload["result"]["analysis_type"] == "herb"
    assert second_payload["result"]["query"] == "黄芪"
    assert second_payload["result"]["research_protocol"] == RESEARCH_PROTOCOL
    assert second_payload["result"]["readiness"]["protocol_complete"] is True
    assert second_payload["result"]["readiness"]["formal_network_ready"] is False
    assert "mock" in " ".join(second_payload["result"]["readiness"]["blocking_reasons"])
    assert len(second_payload["result"]["chains"]) >= 1
    first_chain = second_payload["result"]["chains"][0]
    assert first_chain["related_entity_ids"]
    assert all(entity_id for entity_id in first_chain["related_entity_ids"])


def test_network_result_separates_compound_targets_from_unavailable_disease_targets():
    client = TestClient(app)
    create_response = client.post(
        "/api/network/analyze",
        json={
            "query": "黄芪",
            "analysis_type": "herb",
            "research_protocol": RESEARCH_PROTOCOL,
        },
    )
    task_id = create_response.json()["task_id"]

    client.get(f"/api/network/result/{task_id}")
    payload = client.get(f"/api/network/result/{task_id}").json()["result"]
    lineage = payload["target_lineage"]

    assert lineage["observation_unit"] == "mixed"
    assert lineage["disease_observation_unit"] == "source_record"
    assert lineage["compound_observation_unit"] == "source_record"
    assert lineage["intersection_observation_unit"] == "canonical_symbol_derivation"
    assert lineage["disease_targets"] == []
    assert lineage["intersection_targets"] == []
    assert lineage["compound_targets"]
    assert lineage["disease_target_count"] == 0
    assert lineage["compound_target_count"] == len(
        {row["canonical_symbol"] for row in lineage["compound_targets"]}
    )
    assert lineage["compound_lineage_row_count"] == len(lineage["compound_targets"])
    assert lineage["intersection_target_count"] == 0
    assert any("独立疾病靶点" in warning for warning in lineage["warnings"])

    first = lineage["compound_targets"][0]
    assert first["raw_identifier"] == first["canonical_symbol"]
    assert first["source_database"] == "qiyan_sample_network"
    assert first["database_version"] is None
    assert first["query_date"] == "2026-07-11"
    assert first["species"] == "Homo sapiens"
    assert first["identifier_mapping"] == "identity_symbol"
    assert first["automatic_status"] == "extracted"
    assert first["adjudication_status"] == "pending"
    assert first["decision"] == "unreviewed"


def test_network_unknown_query_completes_with_honest_empty_result():
    client = TestClient(app)

    create_response = client.post(
        "/api/network/analyze",
        json={
            "query": "不存在的方剂",
            "analysis_type": "formula",
            "research_protocol": RESEARCH_PROTOCOL,
        },
    )
    task_id = create_response.json()["task_id"]

    client.get(f"/api/network/result/{task_id}")
    completed_response = client.get(f"/api/network/result/{task_id}")

    assert completed_response.status_code == 200
    payload = completed_response.json()
    assert payload["status"] == "completed"
    assert payload["result"]["query"] == "不存在的方剂"
    assert payload["result"]["chains"] == []
    assert payload["result"]["enrichment"] is None


def test_network_live_mode_surfaces_provenance_fields(monkeypatch, tmp_path: Path):
    cache_dir = tmp_path / "network_cache"
    prediction_file = tmp_path / "predictions.csv"
    cache_repo = NetworkCacheRepository(cache_dir)
    compound_name = "Astragaloside IV"
    cache_repo.write_json(
        build_network_cache_key(
            provider="tcmsp",
            query="黄芪",
            params={"herb": "黄芪", "analysis_type": "herb"},
        ),
        {"compounds": [{"name": compound_name, "herb": "黄芪"}]},
    )
    cache_repo.write_json(
        build_network_cache_key(
            provider="pubchem",
            query=compound_name,
            params={"compound": compound_name},
        ),
        {"IdentifierList": {"CID": [13943297]}},
    )
    cache_repo.write_json(
        build_network_cache_key(
            provider="chembl",
            query=compound_name,
            params={"compound": compound_name, "pubchem_cid": "13943297"},
        ),
        {
            "activities": [
                {
                    "target_pref_name": "IL6",
                    "target_organism": "Homo sapiens",
                    "pchembl_value": "8.0",
                    "assay_chembl_id": "CHEMBLASSAY-HQ-1",
                }
            ]
        },
    )
    cache_repo.write_json(
        build_network_cache_key(
            provider="kegg",
            query="IL6,TNF",
            params={"genes": "IL6,TNF"},
        ),
        {
            "link_text": "hsa:3569\tpath:hsa04668\nhsa:7124\tpath:hsa04668\n",
            "list_text": "path:hsa04668\tTNF signaling pathway - Homo sapiens (human)\n",
        },
    )
    for symbol, accession, name in [
        ("IL6", "P05231", "Interleukin-6"),
        ("TNF", "P01375", "Tumor necrosis factor"),
    ]:
        cache_repo.write_json(
            build_network_cache_key(
                provider="uniprot",
                query=symbol,
                params={
                    "query": UniProtConnector.build_query(symbol),
                    "fields": "accession,gene_names,protein_name",
                    "format": "json",
                    "size": 1,
                },
            ),
            {
                "results": [
                    {
                        "primaryAccession": accession,
                        "genes": [{"geneName": {"value": symbol}}],
                        "proteinDescription": {"recommendedName": {"fullName": {"value": name}}},
                    }
                ]
            },
        )
    cache_repo.write_json(
        build_network_cache_key(
            provider="string",
            query="IL6,TNF",
            params={"identifiers": "IL6\rTNF", "species": 9606, "required_score": 400},
        ),
        "preferredName_A\tpreferredName_B\tscore\nIL6\tTNF\t0.982\n",
    )
    prediction_file.write_text(
        "compound,target_symbol,score,source,source_record_id,retrieved_at\n"
        f"{compound_name},TNF,0.72,SwissTargetPrediction,swiss-hq-1,2026-06-08T00:00:00Z\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("QIYAN_NETWORK_DATA_PROVIDER", "live")
    monkeypatch.setenv("QIYAN_NETWORK_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("QIYAN_NETWORK_TARGET_PREDICTION_FILE", str(prediction_file))
    get_settings.cache_clear()
    client = TestClient(app)

    create_response = client.post(
        "/api/network/analyze",
        json={
            "query": "黄芪",
            "analysis_type": "herb",
            "research_protocol": RESEARCH_PROTOCOL,
        },
    )
    assert create_response.status_code == 202
    accepted = create_response.json()
    assert accepted["data_mode"] == "live"
    task_id = accepted["task_id"]

    client.get(f"/api/network/result/{task_id}")
    completed_response = client.get(f"/api/network/result/{task_id}")
    assert completed_response.status_code == 200
    payload = completed_response.json()
    assert payload["data_mode"] == "live"
    assert payload["status"] == "completed"
    assert payload["error"] is None
    assert isinstance(payload["warnings"], list)
    assert payload["result"]["data_mode"] == "live"
    assert len(payload["result"]["pipeline_steps"]) >= 1
    assert len(payload["result"]["data_sources"]) >= 1
    first_chain = payload["result"]["chains"][0]
    assert first_chain["target_evidence_type"] in {"known_activity", "predicted", "mixed"}
    assert isinstance(first_chain["evidence_refs"], list)
    get_settings.cache_clear()


def test_network_live_mode_returns_failed_state_when_no_live_chain_can_be_built(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("QIYAN_NETWORK_DATA_PROVIDER", "live")
    monkeypatch.setenv("QIYAN_NETWORK_CACHE_DIR", str(tmp_path / "empty_cache"))
    get_settings.cache_clear()
    client = TestClient(app)

    create_response = client.post(
        "/api/network/analyze",
        json={
            "query": "黄芪",
            "analysis_type": "herb",
            "research_protocol": RESEARCH_PROTOCOL,
        },
    )
    task_id = create_response.json()["task_id"]

    client.get(f"/api/network/result/{task_id}")
    completed_response = client.get(f"/api/network/result/{task_id}")

    assert completed_response.status_code == 200
    payload = completed_response.json()
    assert payload["status"] == "failed"
    assert payload["data_mode"] == "live"
    assert payload["result"] is None
    assert payload["error"] == "No live target chains could be assembled."
    assert "No live target chains could be assembled." in payload["warnings"]
    get_settings.cache_clear()


def test_network_result_endpoint_keeps_returning_completed_mock_result_after_completion():
    client = TestClient(app)

    create_response = client.post(
        "/api/network/analyze",
        json={
            "query": "白鲜皮",
            "analysis_type": "herb",
            "research_protocol": RESEARCH_PROTOCOL,
        },
    )
    assert create_response.status_code == 202
    task_id = create_response.json()["task_id"]

    client.get(f"/api/network/result/{task_id}")
    completed_response = client.get(f"/api/network/result/{task_id}")
    repeated_response = client.get(f"/api/network/result/{task_id}")

    assert completed_response.status_code == 200
    assert repeated_response.status_code == 200
    assert completed_response.json()["status"] == "completed"
    assert repeated_response.json()["status"] == "completed"
    assert repeated_response.json()["result"]["query"] == "白鲜皮"


def test_network_result_endpoint_returns_404_for_unknown_task():
    client = TestClient(app)

    response = client.get("/api/network/result/network-missing-task")

    assert response.status_code == 404
    assert response.json() == {"detail": "Network analysis task not found"}


def test_network_analyze_endpoint_rejects_empty_query():
    client = TestClient(app)

    response = client.post(
        "/api/network/analyze",
        json={
            "query": "",
            "analysis_type": "formula",
            "research_protocol": RESEARCH_PROTOCOL,
        },
    )

    assert response.status_code == 422


@pytest.mark.skipif(
    os.environ.get("QIYAN_STATE_BACKEND") == "sqlite",
    reason="JSON file persistence test; SQLite backend persists to DB instead",
)
def test_network_task_state_is_persisted_to_runtime_file(tmp_path: Path, monkeypatch):
    runtime_file = tmp_path / "persisted_tasks.json"
    monkeypatch.setenv("NETWORK_TASKS_RUNTIME_STATE_PATH", str(runtime_file))

    client = TestClient(app)
    create_response = client.post(
        "/api/network/analyze",
        json={
            "query": "消风散",
            "analysis_type": "formula",
            "research_protocol": RESEARCH_PROTOCOL,
        },
    )
    task_id = create_response.json()["task_id"]

    assert runtime_file.exists()
    after_create = json.loads(runtime_file.read_text(encoding="utf-8"))
    assert len(after_create) == 1
    assert after_create[0]["task_id"] == task_id
    assert after_create[0]["status"] == "queued"
    assert after_create[0]["poll_count"] == 0

    client.get(f"/api/network/result/{task_id}")
    after_first_poll = json.loads(runtime_file.read_text(encoding="utf-8"))
    assert after_first_poll[0]["status"] == "running"
    assert after_first_poll[0]["poll_count"] == 1

    # Simulate process restart: rebuild client from scratch; runtime file is the
    # only persistence layer, so completed state must be reachable on next poll.
    fresh_client = TestClient(app)
    second_poll = fresh_client.get(f"/api/network/result/{task_id}")
    assert second_poll.status_code == 200
    assert second_poll.json()["status"] == "completed"

    after_second_poll = json.loads(runtime_file.read_text(encoding="utf-8"))
    assert after_second_poll[0]["status"] == "completed"
    assert after_second_poll[0]["poll_count"] == 2
    first_chain = after_second_poll[0]["result"]["chains"][0]
    # Formula query now expands to constituent herbs via the seed entity graph;
    # the formula label is carried on the chain.formula field instead of herb.
    assert first_chain["formula"] == "消风散"
    assert first_chain["herb"] in {"荆芥", "防风", "牛蒡子"}

    repeated_poll = fresh_client.get(f"/api/network/result/{task_id}")
    assert repeated_poll.status_code == 200
    assert repeated_poll.json()["status"] == "completed"
    after_repeated_poll = json.loads(runtime_file.read_text(encoding="utf-8"))
    assert after_repeated_poll == after_second_poll


def test_network_entities_endpoint_returns_grouped_lookup_payload():
    client = TestClient(app)

    response = client.get("/api/network/entities")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {"herbs", "formulas", "compounds", "targets", "pathways"}
    assert len(payload["herbs"]) == 5
    assert len(payload["formulas"]) == 2
    assert len(payload["compounds"]) == 5
    assert len(payload["targets"]) == 5
    assert len(payload["pathways"]) == 4

    formula_ids = {f["id"] for f in payload["formulas"]}
    assert "formula-xiaofengsan" in formula_ids
    target_ids = {t["id"] for t in payload["targets"]}
    assert "target-flg" in target_ids


def test_network_entities_endpoint_each_entry_has_id_and_display_name():
    client = TestClient(app)

    payload = client.get("/api/network/entities").json()

    for herb in payload["herbs"]:
        assert herb["id"] and herb["name"]
    for formula in payload["formulas"]:
        assert formula["id"] and formula["name"]
    for compound in payload["compounds"]:
        assert compound["id"] and compound["name"]
    for target in payload["targets"]:
        assert target["id"] and target["symbol"] and target["name"]
    for pathway in payload["pathways"]:
        assert pathway["id"] and pathway["name"]


# ── Report endpoint tests ───────────────────────────────────────────────────


def test_report_endpoint_returns_404_for_missing_task():
    client = TestClient(app)

    response = client.get("/api/network/result/network-nonexistent-task/report")

    assert response.status_code == 404
    assert response.json() == {"detail": "Network analysis task not found"}


def test_report_endpoint_returns_202_for_pending_task():
    """A report read must not advance a newly queued task."""
    client = TestClient(app)

    create_response = client.post(
        "/api/network/analyze",
        json={
            "query": "黄芩",
            "analysis_type": "herb",
            "research_protocol": RESEARCH_PROTOCOL,
        },
    )
    assert create_response.status_code == 202
    task_id = create_response.json()["task_id"]
    runtime_file = Path(os.environ["NETWORK_TASKS_RUNTIME_STATE_PATH"])
    before_report = runtime_file.read_text(encoding="utf-8")

    report_response = client.get(f"/api/network/result/{task_id}/report")
    assert report_response.status_code == 202
    assert runtime_file.read_text(encoding="utf-8") == before_report


def test_report_endpoint_returns_202_for_running_task():
    """A report read must not complete a running task."""
    client = TestClient(app)

    create_response = client.post(
        "/api/network/analyze",
        json={
            "query": "黄芪",
            "analysis_type": "herb",
            "research_protocol": RESEARCH_PROTOCOL,
        },
    )
    task_id = create_response.json()["task_id"]

    # First poll advances queued → running
    client.get(f"/api/network/result/{task_id}")
    runtime_file = Path(os.environ["NETWORK_TASKS_RUNTIME_STATE_PATH"])
    before_report = runtime_file.read_text(encoding="utf-8")

    report_response = client.get(f"/api/network/result/{task_id}/report")
    assert report_response.status_code == 202
    assert runtime_file.read_text(encoding="utf-8") == before_report


def test_report_endpoint_returns_markdown_for_completed_task():
    client = TestClient(app)

    create_response = client.post(
        "/api/network/analyze",
        json={
            "query": "黄芩",
            "analysis_type": "herb",
            "research_protocol": RESEARCH_PROTOCOL,
        },
    )
    task_id = create_response.json()["task_id"]

    # Poll twice to reach "completed"
    client.get(f"/api/network/result/{task_id}")
    client.get(f"/api/network/result/{task_id}")
    runtime_file = Path(os.environ["NETWORK_TASKS_RUNTIME_STATE_PATH"])
    before_report = runtime_file.read_text(encoding="utf-8")

    report_response = client.get(f"/api/network/result/{task_id}/report")
    assert report_response.status_code == 200
    assert runtime_file.read_text(encoding="utf-8") == before_report

    text = report_response.text
    assert "# Qiyan Nexus 网络药理学报告导出" in text
    assert "非诊断结论、需结合临床。" in text
    assert "黄芩" in text
    assert "## 链路结果" in text
    assert "## 边界说明" in text


def test_report_endpoint_returns_terminal_error_for_failed_task():
    repo = get_network_task_repository()
    repo.upsert(
        task_id="network-failed-report",
        owner_id="local-preview",
        query="黄芪",
        analysis_type="herb",
        status="failed",
        progress=100,
        poll_count=2,
        result=None,
        error="provider unavailable",
        created_at="2025-01-01T00:00:00",
    )
    before_report = repo.get("network-failed-report")

    response = TestClient(app).get("/api/network/result/network-failed-report/report")

    assert response.status_code == 409
    assert response.json() == {"detail": "provider unavailable"}
    assert repo.get("network-failed-report") == before_report


def test_report_endpoint_returns_500_when_result_is_none():
    repo = get_network_task_repository()
    repo.upsert(
        task_id="network-missing-result",
        owner_id="local-preview",
        query="黄芪",
        analysis_type="herb",
        status="completed",
        progress=100,
        poll_count=2,
        result=None,
        created_at="2025-01-01T00:00:00",
    )

    response = TestClient(app).get("/api/network/result/network-missing-result/report")

    assert response.status_code == 500
    assert response.json() == {"detail": "Task completed but result is missing"}
