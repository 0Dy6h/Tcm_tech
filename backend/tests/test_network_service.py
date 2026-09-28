from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest

from app.repositories.sqlite_network_tasks import SqliteNetworkTaskRepository
from app.schemas.network import (
    NetworkAnalysisResult,
    NetworkChain,
    NetworkCompoundTargetRecord,
    NetworkCompoundTargetVerifiedSnapshot,
    NetworkCompoundTargetVerifyMetadata,
    NetworkDiseaseTargetImport,
    NetworkDiseaseTargetImportSnapshot,
    NetworkDiseaseTargetRecord,
    NetworkDiseaseTargetVerifiedSnapshot,
    NetworkDiseaseTargetVerifyMetadata,
    NetworkResearchProtocol,
    NetworkTaskRecord,
)
from app.services.network_imports import (
    build_verified_compound_import_snapshot,
    build_verified_disease_import_snapshot,
)
from app.services.network_lineage import (
    assess_network_research_readiness,
    build_target_lineage,
)
from app.services.network_queries import (
    get_network_analysis_result,
    get_network_analysis_task,
)
from app.services.network_tasks import (
    _advance_record,
    _build_chains_from_seed,
    create_network_analysis_task,
)

OPEN_TARGETS_FIXTURE = (
    Path(__file__).parent / "data" / "open_targets_graphql_associations_25_06.json"
)
CHEMBL_FIXTURE = Path(__file__).parent / "data" / "chembl_known_activities_34.json"


def _verified_metadata() -> NetworkDiseaseTargetVerifyMetadata:
    return NetworkDiseaseTargetVerifyMetadata(
        source_profile="open_targets_association_v1",
        disease="atopic_dermatitis",
        phenotype="特应性皮炎伴 2 型炎症",
        species="Homo sapiens",
        source_database="Open Targets Platform",
        database_version="25.06",
        source_query_id="EFO_0000274",
        source_query_label="atopic eczema",
        source_query_parameters={"datatype": "overall"},
        query_date="2026-07-11",
        retrieved_at="2026-07-11T08:30:00Z",
        score_name="association_score",
        applied_threshold=0.6,
        threshold_operator="gte",
        identifier_mapping="Ensembl target approvedSymbol",
        identifier_mapping_version="25.06",
        usage_license_note="Open Targets Platform data; see platform terms.",
    )


def _verified_compound_metadata() -> NetworkCompoundTargetVerifyMetadata:
    return NetworkCompoundTargetVerifyMetadata(
        source_profile="chembl_known_activity_v1",
        compound_id="CHEMBL1201587",
        compound_label="Quercetin",
        species="Homo sapiens",
        source_database="ChEMBL",
        database_version="34",
        source_query_id="CHEMBL1201587",
        source_query_label="Quercetin",
        source_query_parameters={
            "assay_organism": "Homo sapiens",
            "standard_type": "IC50",
            "pchembl_value_min": 6.0,
        },
        query_date="2026-07-12",
        retrieved_at="2026-07-12T08:30:00Z",
        score_name="pchembl_value",
        applied_threshold=6.0,
        threshold_operator="gte",
        identifier_mapping="ChEMBL target component gene symbol",
        identifier_mapping_version="34",
        usage_license_note="ChEMBL data; see database terms.",
    )


def test_target_snapshot_numeric_fields_reject_boolean_values() -> None:
    with pytest.raises(ValueError, match="source_score must be numeric and not boolean"):
        NetworkDiseaseTargetRecord(
            raw_identifier="ENSG00000136244",
            canonical_symbol="IL6",
            source_record_id="EFO_0000274:ENSG00000136244",
            source_score=True,
        )
    with pytest.raises(ValueError, match="applied_threshold must be numeric and not boolean"):
        NetworkDiseaseTargetImport.model_validate(
            {
                **_verified_metadata().model_dump(mode="json"),
                "applied_threshold": True,
                "records": [],
            }
        )
    with pytest.raises(ValueError, match="applied_threshold must be numeric and not boolean"):
        NetworkDiseaseTargetVerifyMetadata.model_validate(
            {
                **_verified_metadata().model_dump(mode="json"),
                "applied_threshold": True,
            }
        )
    with pytest.raises(ValueError, match="source_score must be numeric and not boolean"):
        NetworkCompoundTargetRecord(
            raw_identifier="CHEMBL1792",
            canonical_symbol="IL6",
            source_record_id="CHEMBL_ACTIVITY_1001",
            source_score=True,
        )


def test_verified_disease_snapshot_requires_raw_artifact_sha256() -> None:
    payload = {
        "source_profile": "open_targets_association_v1",
        "disease": "atopic_dermatitis",
        "phenotype": "特应性皮炎伴 2 型炎症",
        "species": "Homo sapiens",
        "source_database": "Open Targets Platform",
        "database_version": "25.06",
        "source_query_id": "EFO_0000274",
        "source_query_label": "atopic eczema",
        "source_query_parameters": {"datatypes": ["genetic_association"]},
        "query_date": "2026-07-11",
        "retrieved_at": "2026-07-11T08:30:00Z",
        "score_name": "association_score",
        "applied_threshold": 0.6,
        "threshold_operator": "gte",
        "identifier_mapping": "Ensembl target approvedSymbol",
        "identifier_mapping_version": "25.06",
        "records": [],
        "provenance_verification_status": "server_verified_raw_artifact",
        "import_payload_sha256": "a" * 64,
        "source_artifact_filename": "open-targets-25.06.jsonl",
        "source_artifact_media_type": "application/x-ndjson",
        "usage_license_note": "Open Targets Platform data; see platform terms.",
    }

    with pytest.raises(ValueError):
        NetworkDiseaseTargetVerifiedSnapshot.model_validate(payload)
    with pytest.raises(ValueError):
        NetworkDiseaseTargetVerifiedSnapshot.model_validate(
            {**payload, "source_artifact_sha256": "not-a-sha256"}
        )

    snapshot = NetworkDiseaseTargetVerifiedSnapshot.model_validate(
        {**payload, "source_artifact_sha256": "b" * 64}
    )
    assert snapshot.provenance_verification_status == "server_verified_raw_artifact"


def test_verified_snapshot_hashes_raw_bytes_and_server_derived_payload_deterministically() -> None:
    raw_bytes = OPEN_TARGETS_FIXTURE.read_bytes()

    first = build_verified_disease_import_snapshot(
        raw_bytes,
        metadata=_verified_metadata(),
        source_artifact_filename=OPEN_TARGETS_FIXTURE.name,
        source_artifact_media_type="application/x-ndjson",
    )
    second = build_verified_disease_import_snapshot(
        raw_bytes,
        metadata=_verified_metadata(),
        source_artifact_filename=OPEN_TARGETS_FIXTURE.name,
        source_artifact_media_type="application/x-ndjson",
    )
    whitespace_changed = build_verified_disease_import_snapshot(
        raw_bytes + b"\n",
        metadata=_verified_metadata(),
        source_artifact_filename=OPEN_TARGETS_FIXTURE.name,
        source_artifact_media_type="application/x-ndjson",
    )
    usage_note_changed = build_verified_disease_import_snapshot(
        raw_bytes,
        metadata=_verified_metadata().model_copy(
            update={"usage_license_note": "Different operator-recorded usage terms."}
        ),
        source_artifact_filename=OPEN_TARGETS_FIXTURE.name,
        source_artifact_media_type="application/x-ndjson",
    )

    assert first == second
    assert first.source_artifact_sha256 != whitespace_changed.source_artifact_sha256
    assert first.import_payload_sha256 == whitespace_changed.import_payload_sha256
    assert first.import_payload_sha256 != usage_note_changed.import_payload_sha256
    assert first.records == whitespace_changed.records


def test_verified_compound_snapshot_hashes_raw_bytes_and_server_derived_payload() -> None:
    raw_bytes = CHEMBL_FIXTURE.read_bytes()

    first = build_verified_compound_import_snapshot(
        raw_bytes,
        metadata=_verified_compound_metadata(),
        source_artifact_filename=CHEMBL_FIXTURE.name,
        source_artifact_media_type="application/json",
    )
    second = build_verified_compound_import_snapshot(
        raw_bytes,
        metadata=_verified_compound_metadata(),
        source_artifact_filename=CHEMBL_FIXTURE.name,
        source_artifact_media_type="application/json",
    )
    whitespace_changed = build_verified_compound_import_snapshot(
        raw_bytes + b"\n",
        metadata=_verified_compound_metadata(),
        source_artifact_filename=CHEMBL_FIXTURE.name,
        source_artifact_media_type="application/json",
    )
    usage_note_changed = build_verified_compound_import_snapshot(
        raw_bytes,
        metadata=_verified_compound_metadata().model_copy(
            update={"usage_license_note": "Different operator-recorded usage terms."}
        ),
        source_artifact_filename=CHEMBL_FIXTURE.name,
        source_artifact_media_type="application/json",
    )

    assert isinstance(first, NetworkCompoundTargetVerifiedSnapshot)
    assert first == second
    assert first.provenance_verification_status == "server_verified_raw_artifact"
    assert first.source_artifact_sha256 != whitespace_changed.source_artifact_sha256
    assert first.import_payload_sha256 == whitespace_changed.import_payload_sha256
    assert first.import_payload_sha256 != usage_note_changed.import_payload_sha256
    assert [record.canonical_symbol for record in first.records] == ["EGFR", "IL6"]


def test_verified_compound_snapshot_drives_lineage_and_server_derived_intersection() -> None:
    protocol = NetworkResearchProtocol(
        phenotype="特应性皮炎伴 2 型炎症",
        evidence_policy="direct_human_first",
        query_date="2026-07-11",
    )
    disease_snapshot = build_verified_disease_import_snapshot(
        OPEN_TARGETS_FIXTURE.read_bytes(),
        metadata=_verified_metadata(),
        source_artifact_filename=OPEN_TARGETS_FIXTURE.name,
        source_artifact_media_type="application/json",
    )
    compound_metadata = NetworkCompoundTargetVerifyMetadata.model_validate(
        {
            **_verified_compound_metadata().model_dump(mode="json"),
            "query_date": protocol.query_date,
            "retrieved_at": "2026-07-11T08:30:00Z",
        }
    )
    compound_snapshot = build_verified_compound_import_snapshot(
        CHEMBL_FIXTURE.read_bytes(),
        metadata=compound_metadata,
        source_artifact_filename=CHEMBL_FIXTURE.name,
        source_artifact_media_type="application/json",
    )

    lineage = build_target_lineage(
        [],
        protocol,
        "live",
        disease_snapshot,
        compound_target_import=compound_snapshot,
    )

    assert lineage.compound_import_provenance is not None
    assert lineage.compound_import_provenance.provenance_verification_status == (
        "server_verified_raw_artifact"
    )
    assert lineage.compound_target_count == 2
    assert lineage.compound_lineage_row_count == 2
    assert [row.canonical_symbol for row in lineage.compound_targets] == ["EGFR", "IL6"]
    assert {row.database_version for row in lineage.compound_targets} == {"34"}
    assert {row.score_name for row in lineage.compound_targets} == {"pchembl_value"}
    assert {row.applied_threshold for row in lineage.compound_targets} == {6.0}
    assert {row.identifier_mapping for row in lineage.compound_targets} == {
        "ChEMBL target component gene symbol"
    }
    assert {row.source_score for row in lineage.compound_targets} == {6.1, 6.4}
    assert lineage.intersection_target_count == 2
    assert {row.canonical_symbol for row in lineage.intersection_targets} == {"EGFR", "IL6"}
    for intersection in lineage.intersection_targets:
        assert intersection.disease_lineage_row_ids
        assert intersection.compound_lineage_row_ids
    readiness = assess_network_research_readiness(protocol, "live", lineage)
    assert readiness.formal_network_ready is False
    assert not any(
        "compound 来源数据库版本、阈值与标识符映射尚未冻结" in reason
        for reason in readiness.blocking_reasons
    )
    assert any("人工判定" in reason for reason in readiness.blocking_reasons)


def test_imported_compound_snapshot_skips_provider_graph_and_enrichment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disease_metadata = _verified_metadata()
    protocol = NetworkResearchProtocol(
        phenotype=disease_metadata.phenotype,
        evidence_policy="direct_human_first",
        query_date=disease_metadata.query_date,
    )
    disease_snapshot = build_verified_disease_import_snapshot(
        OPEN_TARGETS_FIXTURE.read_bytes(),
        metadata=disease_metadata,
        source_artifact_filename=OPEN_TARGETS_FIXTURE.name,
        source_artifact_media_type="application/json",
    )
    compound_metadata = _verified_compound_metadata().model_copy(
        update={
            "query_date": disease_metadata.query_date,
            "retrieved_at": disease_metadata.retrieved_at,
        }
    )
    compound_snapshot = build_verified_compound_import_snapshot(
        CHEMBL_FIXTURE.read_bytes(),
        metadata=compound_metadata,
        source_artifact_filename=CHEMBL_FIXTURE.name,
        source_artifact_media_type="application/json",
    )
    record = NetworkTaskRecord(
        task_id="network-imported-child",
        source_task_id="network-" + "a" * 32,
        owner_id="reviewer-a",
        query="消风散",
        analysis_type="formula",
        research_protocol=protocol,
        disease_target_import=disease_snapshot,
        compound_target_import=compound_snapshot,
        status="running",
        progress=60,
        poll_count=1,
        data_mode="live",
        created_at="2026-07-15T00:00:00+00:00",
    )

    def _provider_must_not_run(_: object) -> object:
        pytest.fail("imported compound snapshot must not invoke a provider-derived graph")

    monkeypatch.setattr("app.services.network.select_network_provider", _provider_must_not_run)

    completed = _advance_record(record)

    assert completed.status == "completed"
    assert completed.result is not None
    assert completed.result.source_task_id == record.source_task_id
    assert completed.result.chains == []
    assert completed.result.enrichment is None
    assert completed.result.data_sources == []
    assert completed.result.pipeline_steps == []
    assert any(
        "导入靶点尚未构建可复算的成分-靶点-通路网络闭环" in warning
        for warning in completed.result.warnings
    )
    assert any(
        "导入靶点尚未构建可复算的成分-靶点-通路网络闭环" in reason
        for reason in completed.result.readiness.blocking_reasons
    )


def test_completed_legacy_compound_child_without_parent_link_is_read_only_failed_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_path = tmp_path / "network_tasks_state.json"
    seed_path.write_text("[]\n", encoding="utf-8")
    repo = SqliteNetworkTaskRepository(tmp_path / "network.sqlite3", seed_path=seed_path)
    disease_metadata = _verified_metadata()
    protocol = NetworkResearchProtocol(
        phenotype=disease_metadata.phenotype,
        evidence_policy="direct_human_first",
        query_date=disease_metadata.query_date,
    )
    disease_snapshot = build_verified_disease_import_snapshot(
        OPEN_TARGETS_FIXTURE.read_bytes(),
        metadata=disease_metadata,
        source_artifact_filename=OPEN_TARGETS_FIXTURE.name,
        source_artifact_media_type="application/json",
    )
    compound_metadata = _verified_compound_metadata().model_copy(
        update={
            "query_date": disease_metadata.query_date,
            "retrieved_at": disease_metadata.retrieved_at,
        }
    )
    compound_snapshot = build_verified_compound_import_snapshot(
        CHEMBL_FIXTURE.read_bytes(),
        metadata=compound_metadata,
        source_artifact_filename=CHEMBL_FIXTURE.name,
        source_artifact_media_type="application/json",
    )
    task_id = "network-" + "c" * 32
    lineage = build_target_lineage(
        [],
        protocol,
        "live",
        disease_snapshot,
        compound_target_import=compound_snapshot,
    )
    legacy_result = NetworkAnalysisResult(
        task_id=task_id,
        query="消风散",
        analysis_type="formula",
        research_protocol=protocol,
        target_lineage=lineage,
        data_mode="live",
        chains=[
            NetworkChain(
                herb="荆芥",
                formula="消风散",
                compound="old-provider-compound",
                target="OLD_PROVIDER_TARGET",
                pathway="old provider pathway",
                disease="Atopic dermatitis",
                score=0.9,
                related_entity_ids=[],
            )
        ],
        disclaimer="非诊断结论、需结合临床。",
    )
    repo.upsert(
        task_id=task_id,
        owner_id="reviewer-a",
        query="消风散",
        analysis_type="formula",
        research_protocol=protocol,
        disease_target_import=disease_snapshot,
        compound_target_import=compound_snapshot,
        status="completed",
        progress=100,
        poll_count=2,
        data_mode="live",
        result=legacy_result,
        created_at="2026-07-15T00:00:00+00:00",
    )
    monkeypatch.setattr("app.services.network._get_repository", lambda: repo)

    try:
        before = repo.get(task_id)
        state, payload = get_network_analysis_result(task_id, "reviewer-a")
        report_state, report_payload = get_network_analysis_task(task_id, "reviewer-a")
        after = repo.get(task_id)

        assert before is not None
        assert state == report_state == "ok"
        assert payload is not None and report_payload is not None
        assert payload.status == report_payload.status == "failed"
        assert payload.result is None and report_payload.result is None
        assert payload.error is not None and "父任务链接" in payload.error
        assert after == before
    finally:
        repo.close()


def test_create_network_task_retries_task_id_collision_without_mutating_existing_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_path = tmp_path / "network_tasks_state.json"
    seed_path.write_text("[]\n", encoding="utf-8")
    repo = SqliteNetworkTaskRepository(tmp_path / "network.sqlite3", seed_path=seed_path)
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
    monkeypatch.setattr("app.services.network._get_repository", lambda: repo)
    monkeypatch.setattr("app.services.network.uuid4", lambda: next(generated_ids))

    try:
        accepted = create_network_analysis_task(
            "消风散",
            "formula",
            reviewer_id="reviewer-a",
            research_protocol={
                "disease": "atopic_dermatitis",
                "phenotype": "特应性皮炎伴 2 型炎症",
                "species": "Homo sapiens",
                "evidence_policy": "direct_human_first",
                "query_date": "2026-07-11",
            },
        )

        assert accepted.task_id == f"network-{unique_hex}"
        assert repo.get(collision_task_id) == collision_before
    finally:
        repo.close()


def test_task_record_rejects_source_task_link_without_compound_import() -> None:
    with pytest.raises(ValueError, match="only valid for imported compound child"):
        NetworkTaskRecord(
            task_id="network-" + "a" * 32,
            source_task_id="network-" + "b" * 32,
            owner_id="reviewer-a",
            query="消风散",
            analysis_type="formula",
            status="queued",
            progress=0,
            poll_count=0,
            created_at="2026-07-15T00:00:00+00:00",
        )


def test_verified_disease_source_changes_blocker_but_never_flips_readiness() -> None:
    protocol = NetworkResearchProtocol(
        phenotype="特应性皮炎伴 2 型炎症",
        evidence_policy="direct_human_first",
        query_date="2026-07-11",
    )
    verified = build_verified_disease_import_snapshot(
        OPEN_TARGETS_FIXTURE.read_bytes(),
        metadata=_verified_metadata(),
        source_artifact_filename=OPEN_TARGETS_FIXTURE.name,
        source_artifact_media_type="application/x-ndjson",
    )
    lineage = build_target_lineage([], protocol, "live", verified)

    readiness = assess_network_research_readiness(protocol, "live", lineage)

    assert readiness.formal_network_ready is False
    assert any("疾病来源已服务端核验" in reason for reason in readiness.blocking_reasons)
    assert not any("未验证的客户端导入" in reason for reason in readiness.blocking_reasons)
    assert not any("外部数据库版本" in reason for reason in readiness.blocking_reasons)


def test_verified_zero_hit_disease_snapshot_is_not_labeled_as_client_unverified() -> None:
    metadata = _verified_metadata()
    protocol = NetworkResearchProtocol(
        phenotype=metadata.phenotype,
        evidence_policy="direct_human_first",
        query_date=metadata.query_date,
    )
    verified = build_verified_disease_import_snapshot(
        OPEN_TARGETS_FIXTURE.read_bytes(),
        metadata=metadata,
        source_artifact_filename=OPEN_TARGETS_FIXTURE.name,
        source_artifact_media_type="application/json",
    ).model_copy(update={"records": []})

    lineage = build_target_lineage([], protocol, "live", verified)
    readiness = assess_network_research_readiness(protocol, "live", lineage)

    assert lineage.disease_target_count == 0
    assert lineage.intersection_target_count == 0
    assert any(
        "服务端核验的疾病靶点 artifact 在当前阈值下零命中" in warning
        for warning in lineage.warnings
    )
    assert not any("客户端导入声明" in warning for warning in lineage.warnings)
    assert any("疾病靶点集合为空" in reason for reason in readiness.blocking_reasons)


def test_dual_verified_targets_without_overlap_have_an_empty_intersection_blocker() -> None:
    disease_metadata = _verified_metadata()
    protocol = NetworkResearchProtocol(
        phenotype=disease_metadata.phenotype,
        evidence_policy="direct_human_first",
        query_date=disease_metadata.query_date,
    )
    disease_snapshot = build_verified_disease_import_snapshot(
        OPEN_TARGETS_FIXTURE.read_bytes(),
        metadata=disease_metadata,
        source_artifact_filename=OPEN_TARGETS_FIXTURE.name,
        source_artifact_media_type="application/json",
    )
    compound_metadata = _verified_compound_metadata().model_copy(
        update={
            "query_date": disease_metadata.query_date,
            "retrieved_at": disease_metadata.retrieved_at,
        }
    )
    compound_snapshot = build_verified_compound_import_snapshot(
        CHEMBL_FIXTURE.read_bytes(),
        metadata=compound_metadata,
        source_artifact_filename=CHEMBL_FIXTURE.name,
        source_artifact_media_type="application/json",
    ).model_copy(
        update={
            "records": [
                build_verified_compound_import_snapshot(
                    CHEMBL_FIXTURE.read_bytes(),
                    metadata=compound_metadata,
                    source_artifact_filename=CHEMBL_FIXTURE.name,
                    source_artifact_media_type="application/json",
                )
                .records[0]
                .model_copy(update={"canonical_symbol": "TNF"})
            ]
        }
    )

    lineage = build_target_lineage(
        [],
        protocol,
        "live",
        disease_snapshot,
        compound_target_import=compound_snapshot,
    )
    readiness = assess_network_research_readiness(protocol, "live", lineage)

    assert lineage.disease_target_count > 0
    assert lineage.compound_target_count == 1
    assert lineage.intersection_target_count == 0
    assert any("派生交集为空" in reason for reason in readiness.blocking_reasons)


def test_created_network_task_persists_the_research_protocol(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_path = tmp_path / "network_tasks_state.json"
    seed_path.write_text("[]\n", encoding="utf-8")
    repo = SqliteNetworkTaskRepository(tmp_path / "network.sqlite3", seed_path=seed_path)
    monkeypatch.setattr("app.services.network._get_repository", lambda: repo)
    research_protocol = {
        "disease": "atopic_dermatitis",
        "phenotype": "特应性皮炎伴 2 型炎症与皮肤屏障异常",
        "species": "Homo sapiens",
        "evidence_policy": "direct_human_first",
        "query_date": "2026-07-11",
    }

    try:
        accepted = create_network_analysis_task(
            "消风散",
            "formula",
            reviewer_id="reviewer-a",
            research_protocol=research_protocol,
        )

        persisted = repo.get(accepted.task_id)
        assert persisted is not None
        assert persisted.research_protocol.model_dump(mode="json") == research_protocol
    finally:
        repo.close()


def test_create_task_rejects_disease_import_that_does_not_match_protocol(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_path = tmp_path / "network_tasks_state.json"
    seed_path.write_text("[]\n", encoding="utf-8")
    repo = SqliteNetworkTaskRepository(tmp_path / "network.sqlite3", seed_path=seed_path)
    monkeypatch.setattr("app.services.network._get_repository", lambda: repo)

    try:
        with pytest.raises(ValueError, match="must match research_protocol"):
            create_network_analysis_task(
                "消风散",
                "formula",
                reviewer_id="reviewer-a",
                research_protocol={
                    "disease": "atopic_dermatitis",
                    "phenotype": "特应性皮炎伴 2 型炎症",
                    "species": "Homo sapiens",
                    "evidence_policy": "direct_human_first",
                    "query_date": "2026-07-11",
                },
                disease_target_import={
                    "source_profile": "open_targets_association_v1",
                    "disease": "atopic_dermatitis",
                    "phenotype": "特应性皮炎伴皮肤屏障异常",
                    "species": "Homo sapiens",
                    "source_database": "Open Targets Platform",
                    "database_version": "25.06",
                    "source_query_id": "EFO_0000274",
                    "source_query_label": "atopic eczema",
                    "source_query_parameters": {"datatypes": ["genetic_association"]},
                    "query_date": "2026-07-11",
                    "retrieved_at": "2026-07-11T08:30:00Z",
                    "score_name": "association_score",
                    "applied_threshold": 0.6,
                    "threshold_operator": "gte",
                    "identifier_mapping": "Ensembl target approvedSymbol",
                    "identifier_mapping_version": "25.06",
                    "records": [
                        {
                            "raw_identifier": "ENSG00000136244",
                            "canonical_symbol": "IL6",
                            "source_record_id": "EFO_0000274:ENSG00000136244",
                            "source_score": 0.91,
                        }
                    ],
                },
            )
        assert repo.read_all() == []
    finally:
        repo.close()


def test_sqlite_task_with_disease_import_completes_and_round_trips_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_path = tmp_path / "network_tasks_state.json"
    seed_path.write_text("[]\n", encoding="utf-8")
    repo = SqliteNetworkTaskRepository(tmp_path / "network.sqlite3", seed_path=seed_path)
    monkeypatch.setattr("app.services.network._get_repository", lambda: repo)
    protocol = {
        "disease": "atopic_dermatitis",
        "phenotype": "特应性皮炎伴 2 型炎症",
        "species": "Homo sapiens",
        "evidence_policy": "direct_human_first",
        "query_date": "2026-07-11",
    }
    imported = {
        "source_profile": "open_targets_association_v1",
        "disease": "atopic_dermatitis",
        "phenotype": protocol["phenotype"],
        "species": "Homo sapiens",
        "source_database": "Open Targets Platform",
        "database_version": "25.06",
        "source_query_id": "EFO_0000274",
        "source_query_label": "atopic eczema",
        "source_query_parameters": {"datatypes": ["genetic_association"]},
        "query_date": "2026-07-11",
        "retrieved_at": "2026-07-11T08:30:00Z",
        "score_name": "association_score",
        "applied_threshold": 0.6,
        "threshold_operator": "gte",
        "identifier_mapping": "Ensembl target approvedSymbol",
        "identifier_mapping_version": "25.06",
        "records": [
            {
                "raw_identifier": "ENSG00000136244",
                "canonical_symbol": "IL6",
                "source_record_id": "EFO_0000274:ENSG00000136244",
                "source_score": 0.91,
            }
        ],
    }

    try:
        accepted = create_network_analysis_task(
            "消风散",
            "formula",
            reviewer_id="reviewer-a",
            research_protocol=protocol,
            disease_target_import=imported,
        )

        first_state, first = get_network_analysis_result(accepted.task_id, "reviewer-a")
        second_state, second = get_network_analysis_result(accepted.task_id, "reviewer-a")

        assert first_state == second_state == "ok"
        assert first is not None and first.status == "running"
        assert second is not None and second.status == "completed"
        assert second.result is not None
        assert second.result.target_lineage.disease_import_provenance is not None
        persisted = repo.get_owned(accepted.task_id, "reviewer-a")
        assert persisted is not None and persisted.result == second.result
    finally:
        repo.close()


def test_target_lineage_preserves_distinct_source_rows_for_the_same_target() -> None:
    protocol = NetworkResearchProtocol(
        phenotype="特应性皮炎伴 2 型炎症",
        evidence_policy="mixed_exploratory",
        query_date="2026-07-11",
    )
    chains = [
        NetworkChain(
            herb="黄芪",
            compound="槲皮素",
            target="IL6",
            pathway="TNF signaling",
            disease="Atopic dermatitis",
            score=0.91,
            evidence_refs=["CHEMBL-ACT-1"],
            target_evidence_type="known_activity",
        ),
        NetworkChain(
            herb="黄芪",
            compound="黄芪甲苷",
            target="IL6",
            pathway="JAK-STAT signaling",
            disease="Atopic dermatitis",
            score=0.72,
            evidence_refs=["PREDICT-IL6-1"],
            target_evidence_type="predicted",
        ),
    ]

    lineage = build_target_lineage(chains, protocol, "live")

    assert lineage.compound_target_count == 1
    assert lineage.compound_lineage_row_count == 2
    assert len(lineage.compound_targets) == 2
    assert {row.source_record_ids[0] for row in lineage.compound_targets} == {
        "CHEMBL-ACT-1",
        "PREDICT-IL6-1",
    }
    assert {row.source_database for row in lineage.compound_targets} == {
        "ChEMBL",
        "network_live_provider",
    }


def test_disease_lineage_ids_are_stable_across_record_order_and_bind_provenance() -> None:
    protocol = NetworkResearchProtocol(
        phenotype="特应性皮炎伴 2 型炎症",
        evidence_policy="direct_human_first",
        query_date="2026-07-11",
    )
    records = [
        {
            "raw_identifier": "ENSG00000136244",
            "canonical_symbol": "IL6",
            "source_record_id": "OT-IL6-genetic",
            "source_score": 0.91,
        },
        {
            "raw_identifier": "ENSG00000136244",
            "canonical_symbol": "IL6",
            "source_record_id": "OT-IL6-literature",
            "source_score": 0.73,
        },
    ]
    imported = NetworkDiseaseTargetImportSnapshot(
        source_profile="open_targets_association_v1",
        disease="atopic_dermatitis",
        phenotype=protocol.phenotype,
        species=protocol.species,
        source_database="Open Targets Platform",
        database_version="25.06",
        source_query_id="EFO_0000274",
        source_query_label="atopic eczema",
        source_query_parameters={"datatypes": ["genetic_association", "literature"]},
        query_date=protocol.query_date,
        retrieved_at="2026-07-11T08:30:00Z",
        score_name="association_score",
        applied_threshold=0.6,
        threshold_operator="gte",
        identifier_mapping="Ensembl target approvedSymbol",
        identifier_mapping_version="25.06",
        records=records,
        provenance_verification_status="unverified_client_import",
        import_payload_sha256="a" * 64,
    )
    chains = [
        NetworkChain(
            herb="荆芥",
            formula="消风散",
            compound="槲皮素",
            target="IL6",
            pathway="PI3K-Akt signaling",
            disease="Atopic dermatitis",
            score=0.87,
            related_entity_ids=["target-il6"],
        )
    ]

    original = build_target_lineage(chains, protocol, "mock", imported)
    reordered = build_target_lineage(
        chains,
        protocol,
        "mock",
        imported.model_copy(update={"records": list(reversed(imported.records))}),
    )
    version_changed = build_target_lineage(
        chains,
        protocol,
        "mock",
        imported.model_copy(update={"database_version": "25.07"}),
    )

    original_ids = {
        row.source_record_ids[0]: row.lineage_row_id for row in original.disease_targets
    }
    reordered_ids = {
        row.source_record_ids[0]: row.lineage_row_id for row in reordered.disease_targets
    }
    assert original_ids == reordered_ids
    assert (
        original.intersection_targets[0].lineage_row_id
        == reordered.intersection_targets[0].lineage_row_id
    )
    assert {row.lineage_row_id for row in version_changed.disease_targets}.isdisjoint(
        set(original_ids.values())
    )


def test_formula_query_expands_to_constituent_herbs():
    chains = _build_chains_from_seed("消风散", "formula")

    assert len(chains) >= 1
    assert all(chain.formula == "消风散" for chain in chains)
    # 消风散 = 荆芥 + 防风 + 牛蒡子 in seed; chains must come from this set.
    constituent_herbs = {"荆芥", "防风", "牛蒡子"}
    assert {chain.herb for chain in chains} <= constituent_herbs
    # Chains are scored 0-1 and sorted desc; top should match the curated seed.
    scores = [chain.score for chain in chains]
    assert scores == sorted(scores, reverse=True)
    assert chains[0].disease == "Atopic dermatitis"


def test_herb_query_restricts_chains_to_that_herb_only():
    chains = _build_chains_from_seed("黄芪", "herb")

    assert len(chains) >= 1
    assert all(chain.herb == "黄芪" for chain in chains)
    assert all(chain.formula is None for chain in chains)


def test_unknown_query_returns_no_chains_instead_of_inventing_relationships():
    chains = _build_chains_from_seed("不存在的方剂", "formula")

    assert chains == []


def test_chain_count_capped_to_max_five():
    chains = _build_chains_from_seed("消风散", "formula")
    assert len(chains) <= 5


def test_network_chains_include_entity_ids_for_frontend_chips():
    chains = _build_chains_from_seed("消风散", "formula")

    assert len(chains) >= 1
    first = chains[0]
    assert "herb-" in first.related_entity_ids[0]
    assert first.related_entity_ids[1].startswith("compound-")
    assert first.related_entity_ids[2].startswith("target-")
    assert first.related_entity_ids[3].startswith("pathway-")


def test_concurrent_sqlite_polls_advance_without_losing_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_path = tmp_path / "network_tasks_state.json"
    seed_path.write_text("[]\n", encoding="utf-8")
    repo = SqliteNetworkTaskRepository(tmp_path / "network.sqlite3", seed_path=seed_path)
    task_id = "network-concurrent-poll"
    repo.upsert(
        task_id=task_id,
        query="黄芪",
        analysis_type="herb",
        status="queued",
        progress=0,
        poll_count=0,
        result=None,
        created_at="2025-01-01T00:00:00",
    )

    reads_complete = Barrier(2)

    class SynchronizedReadRepository:
        # Regression trap: the correct service path calls atomic ``advance`` and
        # never reaches this barrier. If it regresses to separate get/upsert
        # calls, both workers deterministically read poll_count=0 before either
        # can write, reproducing the original lost-update race.
        def get(self, current_task_id: str):
            record = repo.get(current_task_id)
            reads_complete.wait()
            return record

        def get_owned(self, current_task_id: str, owner_id: str):
            record = repo.get_owned(current_task_id, owner_id)
            reads_complete.wait()
            return record

        def advance(self, current_task_id: str, owner_id: str, transition):
            return repo.advance(current_task_id, owner_id, transition)

        def list_assembly_plans(self, current_task_id: str, owner_id: str):
            return repo.list_assembly_plans(current_task_id, owner_id)

        def upsert(self, **kwargs):
            return repo.upsert(**kwargs)

    synchronized_repo = SynchronizedReadRepository()
    monkeypatch.setattr("app.services.network._get_repository", lambda: synchronized_repo)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _: get_network_analysis_result(task_id), range(2)))

        assert {response.status for _, response in responses if response is not None} == {
            "running",
            "completed",
        }
        persisted = repo.get(task_id)
        assert persisted is not None
        assert persisted.poll_count == 2
        assert persisted.status == "completed"
        assert persisted.progress == 100
        assert persisted.result is not None
        assert persisted.result.task_id == task_id
    finally:
        repo.close()


def test_failed_network_task_is_terminal_and_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_path = tmp_path / "network_tasks_state.json"
    seed_path.write_text("[]\n", encoding="utf-8")
    repo = SqliteNetworkTaskRepository(tmp_path / "network.sqlite3", seed_path=seed_path)
    task_id = "network-failed-terminal"
    repo.upsert(
        task_id=task_id,
        owner_id="reviewer-a",
        query="黄芪",
        analysis_type="herb",
        status="failed",
        progress=100,
        poll_count=2,
        result=None,
        error="provider unavailable",
        created_at="2025-01-01T00:00:00",
    )
    monkeypatch.setattr("app.services.network._get_repository", lambda: repo)

    try:
        before = repo.get(task_id)
        first_state, first_response = get_network_analysis_result(task_id, "reviewer-a")
        second_state, second_response = get_network_analysis_result(task_id, "reviewer-a")
        after = repo.get(task_id)

        assert before is not None
        assert first_state == second_state == "ok"
        assert first_response is not None and first_response.status == "failed"
        assert second_response is not None and second_response.status == "failed"
        assert after == before
    finally:
        repo.close()
