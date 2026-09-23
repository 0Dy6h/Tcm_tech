import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from app.core.canonical_json import canonical_json_sha256
from app.core.config import get_settings
from app.repositories.network_entities import NetworkEntityRepository
from app.repositories.runtime_storage import get_network_task_repository
from app.schemas.network import (
    AnalysisType,
    DataMode,
    EvidenceLevel,
    EvidencePolicy,
    ManualAdjudicationDecision,
    NetworkAdjudicationCounts,
    NetworkAdjudicationCurrentEntry,
    NetworkAdjudicationRequest,
    NetworkAdjudicationSummary,
    NetworkAnalysisResult,
    NetworkAnalyzeAccepted,
    NetworkAnalyzeRequest,
    NetworkAssemblyConsumeAccepted,
    NetworkAssemblyConsumeRequest,
    NetworkAssemblyConsumptionProjection,
    NetworkAssemblyConsumptionRecord,
    NetworkAssemblyGateBlocker,
    NetworkAssemblyGateProjection,
    NetworkAssemblyOutput,
    NetworkAssemblyPlan,
    NetworkAssemblyPlanAuditView,
    NetworkAssemblyPlanSummary,
    NetworkAssemblySelectedIntersection,
    NetworkChain,
    NetworkCompoundTargetImportProvenance,
    NetworkCompoundTargetSnapshot,
    NetworkCompoundTargetVerifiedSnapshot,
    NetworkCompoundTargetVerifyMetadata,
    NetworkDiseaseTargetImport,
    NetworkDiseaseTargetImportProvenance,
    NetworkDiseaseTargetImportSnapshot,
    NetworkDiseaseTargetSnapshot,
    NetworkDiseaseTargetVerifiedSnapshot,
    NetworkDiseaseTargetVerifyMetadata,
    NetworkResearchProtocol,
    NetworkResearchReadiness,
    NetworkResultResponse,
    NetworkTargetAdjudication,
    NetworkTargetAdjudicationRecord,
    NetworkTargetIntersectionRow,
    NetworkTargetLineage,
    NetworkTargetLineageRow,
    NetworkTaskListResponse,
    NetworkTaskRecord,
    NetworkTaskSummary,
    OmicsAdjudicationContext,
    TargetEvidenceOrigin,
    TaskStatus,
)
from app.schemas.network_entities import (
    Compound,
    NetworkEntitiesResponse,
    Pathway,
    Target,
)
from app.services.enrichment import build_enrichment_result
from app.services.network_chembl import ChEMBLRawArtifactConnector
from app.services.network_omics import (
    OmicsSnapshotConflictError,
    OmicsVerificationBlockedError,
    compute_omics_deg_projection,
)
from app.services.network_open_targets import OpenTargetsRawArtifactConnector
from app.services.network_providers import select_network_provider
from app.services.rag import DISCLAIMER

if TYPE_CHECKING:
    from app.repositories.protocols import NetworkTaskRepositoryProtocol

_MAX_CHAINS_PER_QUERY = 5
_IMPORTED_COMPOUND_SNAPSHOT_BLOCKER = "导入靶点尚未构建可复算的成分-靶点-通路网络闭环。"
_UNLINKED_COMPOUND_CHILD_ERROR = "成分靶点导入缺少不可变的疾病父任务链接，已失败关闭。"


def _get_repository() -> "NetworkTaskRepositoryProtocol":
    return get_network_task_repository()


def _build_chains_from_seed(
    query: str,
    analysis_type: AnalysisType,
    entity_repo: NetworkEntityRepository | None = None,
) -> list[NetworkChain]:
    repo = entity_repo or NetworkEntityRepository()
    compounds = repo.list_compounds()
    targets_by_id: dict[str, Target] = {t.id: t for t in repo.list_targets()}
    pathways_by_id: dict[str, Pathway] = {p.id: p for p in repo.list_pathways()}
    compounds_by_id: dict[str, Compound] = {c.id: c for c in compounds}

    herb_id_to_name: dict[str, str] = {herb.id: herb.name for herb in repo.list_herbs()}
    formula_label: str | None = None
    allowed_herb_ids: set[str] | None = None

    if analysis_type == "formula":
        formula = repo.find_formula_by_query(query)
        if formula is None:
            return []
        formula_label = formula.name
        allowed_herb_ids = set(formula.herb_ids)
    else:
        herb = repo.find_herb_by_query(query)
        if herb is None:
            return []
        allowed_herb_ids = {herb.id}

    candidate_chains: list[tuple[NetworkChain, float]] = []
    for edge in repo.list_chains():
        compound = compounds_by_id.get(edge.compound_id)
        target = targets_by_id.get(edge.target_id)
        pathway = pathways_by_id.get(edge.pathway_id)
        if compound is None or target is None or pathway is None:
            continue
        candidate_herb_ids = compound.herb_ids
        if allowed_herb_ids is not None:
            candidate_herb_ids = [hid for hid in candidate_herb_ids if hid in allowed_herb_ids]
        for herb_id in candidate_herb_ids:
            herb_name = herb_id_to_name.get(herb_id)
            if not herb_name:
                continue
            chain = NetworkChain(
                herb=herb_name,
                formula=formula_label,
                compound=compound.name,
                target=target.symbol,
                pathway=pathway.name,
                disease=edge.disease,
                score=edge.score,
                related_entity_ids=[herb_id, compound.id, target.id, pathway.id],
            )
            candidate_chains.append((chain, edge.score))

    candidate_chains.sort(key=lambda pair: pair[1], reverse=True)
    return [chain for chain, _ in candidate_chains[:_MAX_CHAINS_PER_QUERY]]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_sha256(payload: Any) -> str:
    # Shared with the repository backends so write-time and consume-time
    # recomputation of bound hashes always agree (qiyan_canonical_json_v1).
    return canonical_json_sha256(payload)


def _build_import_snapshot(
    imported: NetworkDiseaseTargetImport,
) -> NetworkDiseaseTargetImportSnapshot:
    payload = imported.model_dump(mode="json")
    return NetworkDiseaseTargetImportSnapshot.model_validate(
        {
            **payload,
            "provenance_verification_status": "unverified_client_import",
            "import_payload_sha256": _canonical_sha256(payload),
        }
    )


def build_verified_disease_import_snapshot(
    raw_bytes: bytes,
    *,
    metadata: NetworkDiseaseTargetVerifyMetadata,
    source_artifact_filename: str,
    source_artifact_media_type: str,
) -> NetworkDiseaseTargetVerifiedSnapshot:
    records = OpenTargetsRawArtifactConnector.parse_open_targets_associations(
        raw_bytes, expected=metadata
    )
    imported_payload = {
        **metadata.model_dump(mode="json"),
        "records": [record.model_dump(mode="json") for record in records],
    }
    return NetworkDiseaseTargetVerifiedSnapshot.model_validate(
        {
            **imported_payload,
            "provenance_verification_status": "server_verified_raw_artifact",
            "import_payload_sha256": _canonical_sha256(imported_payload),
            "source_artifact_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "source_artifact_filename": Path(source_artifact_filename).name,
            "source_artifact_media_type": source_artifact_media_type,
        }
    )


def build_verified_compound_import_snapshot(
    raw_bytes: bytes,
    *,
    metadata: NetworkCompoundTargetVerifyMetadata,
    source_artifact_filename: str,
    source_artifact_media_type: str,
) -> NetworkCompoundTargetVerifiedSnapshot:
    records = sorted(
        ChEMBLRawArtifactConnector.parse_known_activities(raw_bytes, expected=metadata),
        key=lambda record: (
            record.canonical_symbol,
            record.source_record_id,
            record.raw_identifier,
        ),
    )
    imported_payload = {
        **metadata.model_dump(mode="json"),
        "records": [record.model_dump(mode="json") for record in records],
    }
    return NetworkCompoundTargetVerifiedSnapshot.model_validate(
        {
            **imported_payload,
            "provenance_verification_status": "server_verified_raw_artifact",
            "import_payload_sha256": _canonical_sha256(imported_payload),
            "source_artifact_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "source_artifact_filename": Path(source_artifact_filename).name,
            "source_artifact_media_type": source_artifact_media_type,
        }
    )


def _persist_verified_raw_artifact(raw_bytes: bytes, artifact_sha256: str) -> Path:
    configured_dir = os.environ.get("NETWORK_RAW_ARTIFACT_DIR")
    artifact_dir = (
        Path(configured_dir)
        if configured_dir
        else Path(__file__).resolve().parents[2] / "data" / "runtime" / "network_raw_artifacts"
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"{artifact_sha256}.json"
    if (
        artifact_path.exists()
        and hashlib.sha256(artifact_path.read_bytes()).hexdigest() == artifact_sha256
    ):
        return artifact_path
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=artifact_dir,
            prefix=f".{artifact_sha256}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(raw_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        if hashlib.sha256(temporary_path.read_bytes()).hexdigest() != artifact_sha256:
            raise ValueError("temporary raw artifact hash does not match expected bytes")
        os.replace(temporary_path, artifact_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return artifact_path


def _build_lineage_row_id(set_name: str, row: NetworkTargetLineageRow) -> str:
    identity_payload = {
        "set_kind": set_name,
        "source_database": row.source_database,
        "database_version": row.database_version,
        "source_query": row.source_query,
        "query_date": row.query_date.isoformat(),
        "retrieved_at": row.retrieved_at,
        "species": row.species,
        "source_record_ids": sorted(row.source_record_ids),
        "raw_identifier": row.raw_identifier,
        "canonical_symbol": row.canonical_symbol,
        "source_score": row.source_score,
        "score_name": row.score_name,
        "applied_threshold": row.applied_threshold,
        "threshold_operator": row.threshold_operator,
        "identifier_mapping": row.identifier_mapping,
        "identifier_mapping_version": row.identifier_mapping_version,
    }
    return f"{set_name}-{_canonical_sha256(identity_payload)}"


def _build_intersection_row(
    symbol: str,
    research_protocol: NetworkResearchProtocol,
    disease_targets: list[NetworkTargetLineageRow],
    compound_targets: list[NetworkTargetLineageRow],
) -> NetworkTargetIntersectionRow:
    disease_row_ids = sorted(
        row.lineage_row_id
        for row in disease_targets
        if row.canonical_symbol == symbol and row.lineage_row_id is not None
    )
    compound_row_ids = sorted(
        row.lineage_row_id
        for row in compound_targets
        if row.canonical_symbol == symbol and row.lineage_row_id is not None
    )
    identity_payload = {
        "derivation": "canonical_symbol_exact_match_v1",
        "canonical_symbol": symbol,
        "disease_lineage_row_ids": disease_row_ids,
        "compound_lineage_row_ids": compound_row_ids,
    }
    return NetworkTargetIntersectionRow(
        lineage_row_id=f"intersection-{_canonical_sha256(identity_payload)}",
        canonical_symbol=symbol,
        query_date=research_protocol.query_date,
        species=research_protocol.species,
        disease_lineage_row_ids=disease_row_ids,
        compound_lineage_row_ids=compound_row_ids,
    )


def _select_data_mode() -> DataMode:
    provider_name = get_settings().network_data_provider.strip().lower()
    return "live" if provider_name == "live" else "mock"


def assess_network_research_readiness(
    research_protocol: NetworkResearchProtocol | None,
    data_mode: DataMode,
    target_lineage: NetworkTargetLineage | None = None,
) -> NetworkResearchReadiness:
    if research_protocol is None:
        return NetworkResearchReadiness()

    blocking_reasons = ["compound-target 边尚未完成人工判定。"]
    if target_lineage is None or target_lineage.compound_import_provenance is None:
        blocking_reasons.insert(0, "compound 来源数据库版本、阈值与标识符映射尚未冻结。")
    if data_mode == "mock":
        blocking_reasons.insert(0, "当前任务使用 mock 数据，不能进入正式网络药理学研究。")
    if target_lineage is not None:
        if target_lineage.compound_import_provenance is not None:
            blocking_reasons.append(_IMPORTED_COMPOUND_SNAPSHOT_BLOCKER)
        if target_lineage.disease_import_provenance is None:
            blocking_reasons.append("缺少独立疾病靶点集合，不能计算派生候选交集。")
        elif (
            target_lineage.disease_import_provenance.provenance_verification_status
            == "unverified_client_import"
        ):
            blocking_reasons.append(
                "疾病靶点来自未验证的客户端导入，尚未通过服务端 connector 或原始快照校验。"
            )
            if not target_lineage.disease_targets:
                blocking_reasons.append(
                    "客户端导入声明疾病靶点查询在当前阈值下零命中，来源与查询执行未验证。"
                )
        elif (
            target_lineage.disease_import_provenance.provenance_verification_status
            == "server_verified_raw_artifact"
        ):
            if target_lineage.compound_import_provenance is None:
                blocking_reasons.append(
                    "疾病来源已服务端核验；compound 来源保真、阈值与人工 adjudication 未完成，不能进入正式研究状态。"
                )
            else:
                blocking_reasons.append(
                    "疾病与 compound 来源已服务端核验；逐边人工 adjudication 未完成，不能进入正式研究状态。"
                )
        if (
            target_lineage.disease_import_provenance is not None
            and not target_lineage.disease_targets
        ):
            blocking_reasons.append("疾病靶点集合为空，无法形成可供人工判定的疾病-成分网络。")
        if (
            target_lineage.disease_import_provenance is not None
            and target_lineage.compound_import_provenance is not None
            and not target_lineage.intersection_targets
        ):
            blocking_reasons.append("疾病与成分靶点的派生交集为空，无法进入正式网络药理学研究。")
        if any(row.database_version is None for row in target_lineage.compound_targets):
            blocking_reasons.append("至少一个成分靶点来源缺少数据库版本。")
        if any(row.adjudication_status == "pending" for row in target_lineage.compound_targets):
            blocking_reasons.append("成分-靶点记录尚未完成人工判定。")
        if any(row.adjudication_status == "pending" for row in target_lineage.disease_targets):
            blocking_reasons.append("疾病靶点记录尚未完成人工判定。")
        if any(row.adjudication_status == "pending" for row in target_lineage.intersection_targets):
            blocking_reasons.append("派生交集记录尚未完成人工判定。")
    return NetworkResearchReadiness(
        protocol_complete=True,
        formal_network_ready=False,
        blocking_reasons=blocking_reasons,
    )


def build_target_lineage(
    chains: list[NetworkChain],
    research_protocol: NetworkResearchProtocol | None,
    data_mode: DataMode,
    disease_target_import: NetworkDiseaseTargetSnapshot | None = None,
    compound_target_import: NetworkCompoundTargetSnapshot | None = None,
) -> NetworkTargetLineage:
    if research_protocol is None:
        return NetworkTargetLineage(warnings=["缺少研究协议，不能建立靶点 lineage。"])

    if compound_target_import is not None:
        compound_targets: list[NetworkTargetLineageRow] = []
        for record in sorted(
            compound_target_import.records,
            key=lambda item: (item.canonical_symbol, item.source_record_id, item.raw_identifier),
        ):
            row = NetworkTargetLineageRow(
                raw_identifier=record.raw_identifier,
                canonical_symbol=record.canonical_symbol,
                source_database=compound_target_import.source_database,
                database_version=compound_target_import.database_version,
                source_query=compound_target_import.source_query_id,
                query_date=compound_target_import.query_date,
                retrieved_at=compound_target_import.retrieved_at.isoformat(),
                species=compound_target_import.species,
                source_score=record.source_score,
                applied_threshold=compound_target_import.applied_threshold,
                threshold_operator=compound_target_import.threshold_operator,
                score_name=compound_target_import.score_name,
                identifier_mapping=compound_target_import.identifier_mapping,
                identifier_mapping_version=compound_target_import.identifier_mapping_version,
                evidence_origin="known_activity",
                source_record_ids=[record.source_record_id],
            )
            compound_targets.append(
                row.model_copy(update={"lineage_row_id": _build_lineage_row_id("compound", row)})
            )
    else:
        rows_by_key: dict[tuple[str, str, str], NetworkTargetLineageRow] = {}
        for chain in chains:
            canonical_symbol = chain.target.strip()
            if not canonical_symbol:
                continue
            source_record_ids = list(chain.evidence_refs)
            if not source_record_ids:
                source_record_ids = [
                    entity_id
                    for entity_id in chain.related_entity_ids
                    if entity_id.startswith("target-")
                ]
            if data_mode == "mock":
                source_database = "qiyan_sample_network"
                evidence_origin: TargetEvidenceOrigin = "mock"
            else:
                source_database = (
                    "ChEMBL"
                    if chain.target_evidence_type == "known_activity"
                    else "network_live_provider"
                )
                evidence_origin = chain.target_evidence_type

            lineage_record_ids = source_record_ids or [""]
            for source_record_id in lineage_record_ids:
                row_key = (canonical_symbol, source_database, source_record_id)
                existing = rows_by_key.get(row_key)
                if existing is not None:
                    rows_by_key[row_key] = existing.model_copy(
                        update={"source_score": max(existing.source_score or 0, chain.score)}
                    )
                    continue
                rows_by_key[row_key] = NetworkTargetLineageRow(
                    raw_identifier=canonical_symbol,
                    canonical_symbol=canonical_symbol,
                    source_database=source_database,
                    database_version=None,
                    query_date=research_protocol.query_date,
                    species=research_protocol.species,
                    source_score=chain.score,
                    applied_threshold=None,
                    identifier_mapping="identity_symbol",
                    evidence_origin=evidence_origin,
                    source_record_ids=[source_record_id] if source_record_id else [],
                )

        compound_targets = [
            row.model_copy(update={"lineage_row_id": _build_lineage_row_id("compound", row)})
            for row in (rows_by_key[key] for key in sorted(rows_by_key))
        ]
    compound_target_symbols = {row.canonical_symbol for row in compound_targets}
    disease_targets: list[NetworkTargetLineageRow] = []
    if disease_target_import is not None:
        disease_targets = [
            NetworkTargetLineageRow(
                raw_identifier=record.raw_identifier,
                canonical_symbol=record.canonical_symbol,
                source_database=disease_target_import.source_database,
                database_version=disease_target_import.database_version,
                source_query=disease_target_import.source_query_id,
                query_date=disease_target_import.query_date,
                retrieved_at=disease_target_import.retrieved_at.isoformat(),
                species=disease_target_import.species,
                source_score=record.source_score,
                applied_threshold=disease_target_import.applied_threshold,
                threshold_operator=disease_target_import.threshold_operator,
                score_name=disease_target_import.score_name,
                identifier_mapping=disease_target_import.identifier_mapping,
                identifier_mapping_version=disease_target_import.identifier_mapping_version,
                evidence_origin="disease_association",
                source_record_ids=[record.source_record_id],
            )
            for record in disease_target_import.records
        ]
        disease_targets = [
            row.model_copy(update={"lineage_row_id": _build_lineage_row_id("disease", row)})
            for row in disease_targets
        ]
    disease_target_symbols = {row.canonical_symbol for row in disease_targets}
    intersection_target_symbols = disease_target_symbols & compound_target_symbols
    intersection_targets = [
        _build_intersection_row(
            symbol,
            research_protocol,
            disease_targets,
            compound_targets,
        )
        for symbol in sorted(intersection_target_symbols)
    ]
    warnings = ["自动提取不等于人工判定；所有靶点记录默认 adjudication_status=pending。"]
    if disease_target_import is None:
        warnings.insert(
            0,
            "当前 pipeline 未采集独立疾病靶点集合；disease_targets 与 intersection_targets 保持空集。",
        )
    else:
        warnings.insert(
            0,
            "intersection_targets 仅由疾病行与成分行的 canonical symbol 服务端复算产生。",
        )
        if disease_target_import.provenance_verification_status == "server_verified_raw_artifact":
            warnings.insert(
                1,
                "疾病靶点由服务端从原始 artifact 解析；字节哈希与解析一致性不证明 release 选择正确或靶点有生物学意义。",
            )
        else:
            warnings.insert(
                1,
                "疾病靶点来源为客户端声明，payload 哈希只证明导入内容完整性，不证明外部来源真实性。",
            )
        if not disease_targets:
            if (
                disease_target_import.provenance_verification_status
                == "server_verified_raw_artifact"
            ):
                warnings.insert(
                    2,
                    "服务端核验的疾病靶点 artifact 在当前阈值下零命中；"
                    "disease_targets 与 intersection_targets 保持空集，且该一致性不证明查询选择科学有效。",
                )
            else:
                warnings.insert(
                    2,
                    "客户端导入声明疾病靶点查询在当前阈值下零命中，来源与查询执行未验证。",
                )
    disease_import_provenance = None
    if disease_target_import is not None:
        disease_import_provenance = NetworkDiseaseTargetImportProvenance(
            **disease_target_import.model_dump(
                exclude={"records"},
            ),
            record_count=len(disease_target_import.records),
        )
    compound_import_provenance = None
    if compound_target_import is not None:
        compound_import_provenance = NetworkCompoundTargetImportProvenance(
            **compound_target_import.model_dump(exclude={"records"}),
            record_count=len(compound_target_import.records),
        )
    return NetworkTargetLineage(
        disease_import_provenance=disease_import_provenance,
        compound_import_provenance=compound_import_provenance,
        disease_targets=disease_targets,
        compound_targets=compound_targets,
        intersection_targets=intersection_targets,
        disease_target_count=len(disease_target_symbols),
        compound_target_count=len(compound_target_symbols),
        intersection_target_count=len(intersection_target_symbols),
        disease_lineage_row_count=len(disease_targets),
        compound_lineage_row_count=len(compound_targets),
        intersection_lineage_row_count=len(intersection_targets),
        warnings=warnings,
    )


def _create_queued_network_task(
    repo: "NetworkTaskRepositoryProtocol",
    *,
    reviewer_id: str,
    query: str,
    analysis_type: AnalysisType,
    research_protocol: NetworkResearchProtocol | None,
    disease_target_import: NetworkDiseaseTargetSnapshot | None,
    compound_target_import: NetworkCompoundTargetSnapshot | None,
    source_task_id: str | None,
    data_mode: DataMode,
) -> NetworkAnalyzeAccepted:
    """Create a task without allowing an ID collision to mutate another task."""
    for _ in range(3):
        task_id = f"network-{uuid4().hex}"
        task_record = NetworkTaskRecord(
            task_id=task_id,
            source_task_id=source_task_id,
            owner_id=reviewer_id,
            query=query.strip(),
            analysis_type=analysis_type,
            research_protocol=research_protocol,
            disease_target_import=disease_target_import,
            compound_target_import=compound_target_import,
            status="queued",
            progress=0,
            poll_count=0,
            result=None,
            created_at=_now_iso(),
            data_mode=data_mode,
        )
        if repo.create(task_record):
            return NetworkAnalyzeAccepted(
                task_id=task_id,
                status="queued",
                progress=0,
                data_mode=data_mode,
            )
    raise RuntimeError("could not allocate a unique network task id")


def create_network_analysis_task(
    query: str,
    analysis_type: AnalysisType,
    reviewer_id: str = "local-preview",
    research_protocol: NetworkResearchProtocol | dict[str, Any] | None = None,
    disease_target_import: NetworkDiseaseTargetImport | dict[str, Any] | None = None,
) -> NetworkAnalyzeAccepted:
    repo = _get_repository()
    data_mode = _select_data_mode()
    if research_protocol is not None:
        validated_request = NetworkAnalyzeRequest.model_validate(
            {
                "query": query,
                "analysis_type": analysis_type,
                "research_protocol": research_protocol,
                "disease_target_import": disease_target_import,
            }
        )
        validated_protocol: NetworkResearchProtocol | None = validated_request.research_protocol
        validated_disease_import = (
            _build_import_snapshot(validated_request.disease_target_import)
            if validated_request.disease_target_import is not None
            else None
        )
    else:
        if disease_target_import is not None:
            raise ValueError("disease_target_import requires research_protocol")
        validated_protocol = None
        validated_disease_import = None
    return _create_queued_network_task(
        repo,
        reviewer_id=reviewer_id,
        query=query,
        analysis_type=analysis_type,
        research_protocol=validated_protocol,
        disease_target_import=validated_disease_import,
        compound_target_import=None,
        source_task_id=None,
        data_mode=data_mode,
    )


def create_verified_network_analysis_task(
    *,
    query: str,
    analysis_type: AnalysisType,
    reviewer_id: str,
    evidence_policy: EvidencePolicy,
    metadata: NetworkDiseaseTargetVerifyMetadata,
    raw_bytes: bytes,
    source_artifact_filename: str,
    source_artifact_media_type: str,
) -> NetworkAnalyzeAccepted:
    manifest_path = os.environ.get("NETWORK_OPEN_TARGETS_MANIFEST_PATH")
    if not manifest_path:
        raise ValueError("trusted Open Targets artifact manifest is not configured")
    OpenTargetsRawArtifactConnector.validate_trusted_manifest(
        raw_bytes,
        expected=metadata,
        manifest_path=Path(manifest_path),
    )
    snapshot = build_verified_disease_import_snapshot(
        raw_bytes,
        metadata=metadata,
        source_artifact_filename=source_artifact_filename,
        source_artifact_media_type=source_artifact_media_type,
    )
    _persist_verified_raw_artifact(raw_bytes, snapshot.source_artifact_sha256)
    repo = _get_repository()
    data_mode = _select_data_mode()
    return _create_queued_network_task(
        repo,
        reviewer_id=reviewer_id,
        query=query,
        analysis_type=analysis_type,
        research_protocol=NetworkResearchProtocol(
            disease=metadata.disease,
            phenotype=metadata.phenotype,
            species=metadata.species,
            evidence_policy=evidence_policy,
            query_date=metadata.query_date,
        ),
        disease_target_import=snapshot,
        compound_target_import=None,
        source_task_id=None,
        data_mode=data_mode,
    )


def create_verified_compound_network_analysis_task(
    *,
    source_task_id: str,
    reviewer_id: str,
    metadata: NetworkCompoundTargetVerifyMetadata,
    raw_bytes: bytes,
    source_artifact_filename: str,
    source_artifact_media_type: str,
) -> NetworkAnalyzeAccepted:
    manifest_path = os.environ.get("NETWORK_CHEMBL_MANIFEST_PATH")
    if not manifest_path:
        raise ValueError("trusted ChEMBL artifact manifest is not configured")
    repo = _get_repository()
    source_task = repo.get_owned(source_task_id, reviewer_id)
    if source_task is None:
        raise LookupError("network analysis task not found")
    if source_task.research_protocol is None:
        raise ValueError("source task is missing a research protocol")
    if source_task.disease_target_import is None:
        raise ValueError("source task is missing a disease target snapshot")
    if source_task.compound_target_import is not None:
        raise ValueError("source task is already a compound target child task")
    if (
        source_task.disease_target_import.provenance_verification_status
        != "server_verified_raw_artifact"
    ):
        raise ValueError("source task disease target snapshot is not server-verified")
    if metadata.species != source_task.research_protocol.species:
        raise ValueError("compound artifact species must match the source task protocol")
    if metadata.query_date != source_task.research_protocol.query_date:
        raise ValueError("compound artifact query_date must match the source task protocol")

    ChEMBLRawArtifactConnector.validate_trusted_manifest(
        raw_bytes,
        expected=metadata,
        manifest_path=Path(manifest_path),
    )
    snapshot = build_verified_compound_import_snapshot(
        raw_bytes,
        metadata=metadata,
        source_artifact_filename=source_artifact_filename,
        source_artifact_media_type=source_artifact_media_type,
    )
    _persist_verified_raw_artifact(raw_bytes, snapshot.source_artifact_sha256)
    return _create_queued_network_task(
        repo,
        reviewer_id=reviewer_id,
        query=source_task.query,
        analysis_type=source_task.analysis_type,
        research_protocol=source_task.research_protocol,
        disease_target_import=source_task.disease_target_import,
        compound_target_import=snapshot,
        source_task_id=source_task.task_id,
        data_mode=source_task.data_mode,
    )


def _load_go_terms() -> list[Any]:
    """Load GO terms from sample data."""
    path = Path(__file__).resolve().parents[2] / "data" / "network" / "sample_go_terms.json"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        data: list[Any] = json.load(f)
        return data


def _load_kegg_pathways() -> list[Any]:
    """Load KEGG pathways from sample data."""
    path = Path(__file__).resolve().parents[2] / "data" / "network" / "sample_kegg_pathways.json"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        data: list[Any] = json.load(f)
        return data


def _complete_imported_compound_snapshot(record: NetworkTaskRecord) -> NetworkTaskRecord:
    """Expose frozen target sets without inventing a graph or pathway result."""
    target_lineage = build_target_lineage(
        [],
        record.research_protocol,
        record.data_mode,
        record.disease_target_import,
        record.compound_target_import,
    )
    warnings = [*target_lineage.warnings, _IMPORTED_COMPOUND_SNAPSHOT_BLOCKER]
    result_payload = NetworkAnalysisResult(
        task_id=record.task_id,
        source_task_id=record.source_task_id,
        query=record.query,
        analysis_type=record.analysis_type,
        research_protocol=record.research_protocol,
        readiness=assess_network_research_readiness(
            record.research_protocol, record.data_mode, target_lineage
        ),
        target_lineage=target_lineage,
        data_mode=record.data_mode,
        chains=[],
        enrichment=None,
        warnings=warnings,
        disclaimer=DISCLAIMER,
    )
    return record.model_copy(
        update={
            "status": "completed",
            "progress": 100,
            "poll_count": record.poll_count + 1,
            "result": result_payload,
            "error": None,
            "warnings": warnings,
        }
    )


def _advance_record(record: NetworkTaskRecord) -> NetworkTaskRecord:
    if record.status in {"completed", "failed"}:
        return record
    if record.poll_count == 0:
        return record.model_copy(
            update={
                "status": "running",
                "progress": 60,
                "poll_count": record.poll_count + 1,
                "result": None,
            }
        )

    if record.compound_target_import is not None:
        if record.source_task_id is None:
            return record.model_copy(
                update={
                    "status": "failed",
                    "progress": 100,
                    "poll_count": record.poll_count + 1,
                    "result": None,
                    "error": _UNLINKED_COMPOUND_CHILD_ERROR,
                    "warnings": [_UNLINKED_COMPOUND_CHILD_ERROR],
                }
            )
        return _complete_imported_compound_snapshot(record)

    chains = _build_chains_from_seed(record.query, record.analysis_type)

    # Extract target symbols from chains for enrichment analysis
    target_symbols = list({chain.target for chain in chains})

    # Build enrichment result if we have enough targets
    enrichment = None
    if len(target_symbols) >= 2:
        go_terms = _load_go_terms()
        kegg_pathways = _load_kegg_pathways()
        enrichment = build_enrichment_result(target_symbols, go_terms, kegg_pathways)

    provider = select_network_provider(record.data_mode)
    result_payload = provider.build_result(
        task_id=record.task_id,
        query=record.query,
        analysis_type=record.analysis_type,
        chains=chains,
        enrichment=enrichment,
    )
    target_lineage = build_target_lineage(
        result_payload.chains,
        record.research_protocol,
        record.data_mode,
        record.disease_target_import,
        record.compound_target_import,
    )
    # ADR-0015: grade every chain's evidence level deterministically before
    # it is persisted or returned. Mock chains are hard-pinned to the floor.
    result_payload = result_payload.model_copy(
        update={
            "source_task_id": record.source_task_id,
            "chains": grade_chains_evidence(result_payload.chains, data_mode=record.data_mode),
            "research_protocol": record.research_protocol,
            "target_lineage": target_lineage,
            "readiness": assess_network_research_readiness(
                record.research_protocol, record.data_mode, target_lineage
            ),
        }
    )
    if record.data_mode == "live" and not result_payload.chains:
        error_message = "No live target chains could be assembled."
        return record.model_copy(
            update={
                "status": "failed",
                "progress": 100,
                "poll_count": record.poll_count + 1,
                "result": None,
                "error": error_message,
                "warnings": result_payload.warnings,
            }
        )
    return record.model_copy(
        update={
            "status": "completed",
            "progress": 100,
            "poll_count": record.poll_count + 1,
            "result": result_payload,
            "error": None,
            "warnings": result_payload.warnings,
        }
    )


def _result_response(record: NetworkTaskRecord) -> NetworkResultResponse:
    result = record.result
    if result is not None:
        result = _with_omics_evidence_overlay(result, record.adjudications)
    return NetworkResultResponse(
        task_id=record.task_id,
        status=record.status,
        progress=record.progress,
        data_mode=record.data_mode,
        result=result,
        error=record.error,
        warnings=record.warnings,
        adjudication=_adjudication_summary(record),
        assembly_gate=_assembly_gate_projection(record),
    )


def _with_omics_evidence_overlay(
    result: NetworkAnalysisResult,
    adjudications: list[NetworkTargetAdjudication],
) -> NetworkAnalysisResult:
    """Read-time projection: reflect human-confirmed omics validation on chains.

    The stored result is never mutated. Only live-mode chains whose target
    symbol has an omics_confirmed adjudication are upgraded, and only from the
    lower live tiers — ``mock_inferred`` stays mock forever and
    ``experimental`` is never downgraded. Without a human omics confirmation
    there is no code path that produces ``omics_validated``.
    """
    if result.data_mode != "live":
        return result
    latest_by_row: dict[str, NetworkTargetAdjudication] = {}
    for adjudication in adjudications:
        if adjudication.decision == "omics_confirmed" and adjudication.omics_canonical_symbol:
            latest_by_row[adjudication.lineage_row_id] = adjudication
    confirmed_symbols = {
        item.omics_canonical_symbol
        for item in latest_by_row.values()
        if item.omics_canonical_symbol
    }
    if not confirmed_symbols:
        return result
    upgraded_chains = [
        chain.model_copy(update={"evidence_level": "omics_validated"})
        if chain.evidence_level in {"literature_supported", "predicted"}
        and chain.target in confirmed_symbols
        else chain
        for chain in result.chains
    ]
    return result.model_copy(update={"chains": upgraded_chains})


def _lineage_row_ids(result: NetworkAnalysisResult) -> set[str]:
    """Collect every adjudicable lineage row id from the frozen target sets."""
    lineage = result.target_lineage
    row_ids: set[str] = set()
    for target_row in (*lineage.disease_targets, *lineage.compound_targets):
        if target_row.lineage_row_id is not None:
            row_ids.add(target_row.lineage_row_id)
    for intersection_row in lineage.intersection_targets:
        row_ids.add(intersection_row.lineage_row_id)
    return row_ids


def _adjudication_summary(record: NetworkTaskRecord) -> NetworkAdjudicationSummary:
    """Project append-only adjudications over the frozen lineage.

    Latest decision per lineage row wins; reviewer identity is intentionally
    dropped.  Pure projection: never mutates the record or its lineage.
    """
    row_ids = _lineage_row_ids(record.result) if record.result is not None else set()
    latest_by_row: dict[str, NetworkTargetAdjudication] = {}
    for adjudication in record.adjudications:
        if adjudication.lineage_row_id in row_ids:
            latest_by_row[adjudication.lineage_row_id] = adjudication
    counts = NetworkAdjudicationCounts(
        included=sum(1 for item in latest_by_row.values() if item.decision == "included"),
        excluded=sum(1 for item in latest_by_row.values() if item.decision == "excluded"),
        needs_review=sum(1 for item in latest_by_row.values() if item.decision == "needs_review"),
        omics_confirmed=sum(
            1 for item in latest_by_row.values() if item.decision == "omics_confirmed"
        ),
        pending=len(row_ids) - len(latest_by_row),
    )
    current = [
        NetworkAdjudicationCurrentEntry(
            lineage_row_id=row_id,
            decision=latest_by_row[row_id].decision,
            reason=latest_by_row[row_id].reason,
            decided_at=latest_by_row[row_id].decided_at,
        )
        for row_id in sorted(latest_by_row)
    ]
    return NetworkAdjudicationSummary(counts=counts, current=current)


def _latest_adjudications(
    record: NetworkTaskRecord,
) -> dict[str, NetworkTargetAdjudication]:
    row_ids = _lineage_row_ids(record.result) if record.result is not None else set()
    latest_by_row: dict[str, NetworkTargetAdjudication] = {}
    for adjudication in record.adjudications:
        if adjudication.lineage_row_id in row_ids:
            latest_by_row[adjudication.lineage_row_id] = adjudication
    return latest_by_row


def _assembly_plan_summary(
    plan: NetworkAssemblyPlan,
    *,
    consumed_plan_ids: set[str] | None = None,
) -> NetworkAssemblyPlanSummary:
    return NetworkAssemblyPlanSummary(
        plan_id=plan.plan_id,
        canonical_plan_input_sha256=plan.canonical_plan_input_sha256,
        selected_intersection_count=len(plan.selected_intersections),
        created_at=plan.created_at,
        is_consumed=consumed_plan_ids is not None and plan.plan_id in consumed_plan_ids,
    )


def _assembly_gate_blockers(
    record: NetworkTaskRecord,
    parent: NetworkTaskRecord | None,
) -> tuple[list[NetworkAssemblyGateBlocker], list[NetworkAssemblySelectedIntersection]]:
    blockers: list[NetworkAssemblyGateBlocker] = []
    result = record.result
    if record.status != "completed" or result is None:
        blockers.append(NetworkAssemblyGateBlocker(code="task_not_completed"))
        return blockers, []
    if record.source_task_id is None or record.compound_target_import is None:
        blockers.append(NetworkAssemblyGateBlocker(code="not_compound_child"))
    if parent is None or parent.source_task_id is not None or parent.status != "completed":
        blockers.append(NetworkAssemblyGateBlocker(code="broken_parent_link"))
    elif (
        parent.research_protocol is None
        or record.research_protocol is None
        or _canonical_sha256(parent.research_protocol.model_dump(mode="json"))
        != _canonical_sha256(record.research_protocol.model_dump(mode="json"))
    ):
        blockers.append(NetworkAssemblyGateBlocker(code="protocol_mismatch"))

    lineage = result.target_lineage
    disease_provenance = lineage.disease_import_provenance
    compound_provenance = lineage.compound_import_provenance
    if (
        disease_provenance is None
        or disease_provenance.provenance_verification_status != "server_verified_raw_artifact"
        or not disease_provenance.source_artifact_sha256
    ):
        blockers.append(NetworkAssemblyGateBlocker(code="disease_provenance_unverified"))
    if (
        compound_provenance is None
        or compound_provenance.provenance_verification_status != "server_verified_raw_artifact"
        or not compound_provenance.source_artifact_sha256
    ):
        blockers.append(NetworkAssemblyGateBlocker(code="compound_provenance_unverified"))
    if (
        result.chains
        or result.enrichment is not None
        or result.ppi_edges
        or result.data_sources
        or result.pipeline_steps
    ):
        blockers.append(NetworkAssemblyGateBlocker(code="snapshot_only_boundary_violated"))

    row_ids = _lineage_row_ids(result)
    if len(row_ids) > 10_000 or len(record.adjudications) > 100_000:
        blockers.append(NetworkAssemblyGateBlocker(code="assembly_input_capacity_exceeded"))
        return sorted(blockers, key=lambda item: item.code), []
    latest = _latest_adjudications(record)
    incomplete = sorted(
        row_id
        for row_id in row_ids
        if row_id not in latest or latest[row_id].decision == "needs_review"
    )
    if incomplete:
        blockers.append(
            NetworkAssemblyGateBlocker(code="adjudication_incomplete", row_ids=incomplete)
        )

    included_disease = {
        row_id
        for row_id in (row.lineage_row_id for row in lineage.disease_targets if row.lineage_row_id)
        if row_id in latest and latest[row_id].decision == "included"
    }
    included_compound = {
        row_id
        for row_id in (row.lineage_row_id for row in lineage.compound_targets if row.lineage_row_id)
        if row_id in latest and latest[row_id].decision == "included"
    }
    selected: list[NetworkAssemblySelectedIntersection] = []
    missing_backing: list[str] = []
    for row in sorted(lineage.intersection_targets, key=lambda item: item.lineage_row_id):
        decision = latest.get(row.lineage_row_id)
        if decision is None or decision.decision != "included":
            continue
        selected_disease = sorted(set(row.disease_lineage_row_ids) & included_disease)
        selected_compound = sorted(set(row.compound_lineage_row_ids) & included_compound)
        if not selected_disease or not selected_compound:
            missing_backing.append(row.lineage_row_id)
            continue
        selected.append(
            NetworkAssemblySelectedIntersection(
                lineage_row_id=row.lineage_row_id,
                canonical_symbol=row.canonical_symbol,
                frozen_disease_lineage_row_ids=sorted(row.disease_lineage_row_ids),
                frozen_compound_lineage_row_ids=sorted(row.compound_lineage_row_ids),
                selected_disease_lineage_row_ids=selected_disease,
                selected_compound_lineage_row_ids=selected_compound,
            )
        )
    if missing_backing:
        blockers.append(
            NetworkAssemblyGateBlocker(
                code="included_intersection_missing_backing",
                row_ids=sorted(missing_backing),
            )
        )
    if not selected:
        blockers.append(NetworkAssemblyGateBlocker(code="no_included_intersection"))
    return sorted(blockers, key=lambda item: item.code), selected


def _assembly_gate_projection(record: NetworkTaskRecord) -> NetworkAssemblyGateProjection:
    repo = _get_repository()
    parent = (
        repo.get_owned(record.source_task_id, record.owner_id)
        if record.source_task_id is not None and record.owner_id is not None
        else None
    )
    blockers, _ = _assembly_gate_blockers(record, parent)
    plans = (
        repo.list_assembly_plans(record.task_id, record.owner_id)
        if record.owner_id is not None
        else []
    )
    latest = max(plans, key=lambda item: item.plan_sequence) if plans else None
    consumed_plan_ids = (
        {item.plan_id for item in repo.list_assembly_consumptions(record.task_id, record.owner_id)}
        if record.owner_id is not None and plans
        else set()
    )
    return NetworkAssemblyGateProjection(
        state="blocked" if blockers else "assembly_input_ready",
        blockers=blockers,
        latest_plan=(
            _assembly_plan_summary(latest, consumed_plan_ids=consumed_plan_ids)
            if latest is not None
            else None
        ),
    )


def _adjudication_latest_snapshot(
    record: NetworkTaskRecord,
) -> list[dict[str, Any]]:
    """Deterministic latest-wins adjudication snapshot bound into plan hashes.

    Sorted by lineage row id; every entry carries its adjudication_id (whose
    derivation contains a random nonce), so any adjudication append changes
    the snapshot hash — that is the R6 binding of the consumption contract.
    """
    latest = _latest_adjudications(record)
    return [
        {
            "adjudication_id": item.adjudication_id,
            "lineage_row_id": row_id,
            "decision": item.decision,
            "reason": item.reason,
            "decided_at": item.decided_at,
        }
        for row_id, item in sorted(latest.items())
    ]


def _build_assembly_plan(
    record: NetworkTaskRecord,
    parent: NetworkTaskRecord,
    selected: list[NetworkAssemblySelectedIntersection],
) -> NetworkAssemblyPlan:
    if record.result is None or record.source_task_id is None:
        raise ValueError("assembly plan requires a linked frozen result")
    if record.research_protocol is None or parent.research_protocol is None:
        raise ValueError("assembly plan requires matching protocols")
    lineage = record.result.target_lineage
    disease_provenance = lineage.disease_import_provenance
    compound_provenance = lineage.compound_import_provenance
    if (
        disease_provenance is None
        or compound_provenance is None
        or disease_provenance.source_artifact_sha256 is None
        or compound_provenance.source_artifact_sha256 is None
    ):
        raise ValueError("assembly plan requires verified source artifacts")
    adjudication_snapshot = _adjudication_latest_snapshot(record)
    parent_protocol_hash = _canonical_sha256(parent.research_protocol.model_dump(mode="json"))
    child_protocol_hash = _canonical_sha256(record.research_protocol.model_dump(mode="json"))
    plan_input = {
        "policy_id": "source_bound_network_assembly_v1",
        "canonicalization_id": "qiyan_canonical_json_v1",
        "task_id": record.task_id,
        "source_task_id": record.source_task_id,
        "parent_protocol_sha256": parent_protocol_hash,
        "child_protocol_sha256": child_protocol_hash,
        "disease_source_artifact_sha256": disease_provenance.source_artifact_sha256,
        "compound_source_artifact_sha256": compound_provenance.source_artifact_sha256,
        "disease_import_payload_sha256": disease_provenance.import_payload_sha256,
        "compound_import_payload_sha256": compound_provenance.import_payload_sha256,
        "target_lineage_sha256": _canonical_sha256(lineage.model_dump(mode="json")),
        "adjudication_selection_sha256": _canonical_sha256(adjudication_snapshot),
        "selected_intersections": [item.model_dump(mode="json") for item in selected],
    }
    input_hash = _canonical_sha256(plan_input)
    return NetworkAssemblyPlan.model_validate(
        {
            "plan_id": f"assembly-plan-{input_hash}",
            **plan_input,
            "canonical_plan_input_sha256": input_hash,
            "plan_sequence": 1,
            "created_at": _now_iso(),
        }
    )


def seal_network_assembly_plan(
    task_id: str,
    reviewer_id: str,
) -> tuple[str, NetworkAssemblyPlan | NetworkAssemblyGateProjection | None]:
    repo = _get_repository()
    record = repo.get_owned(task_id, reviewer_id)
    if record is None:
        return "not_found", None
    parent = (
        repo.get_owned(record.source_task_id, reviewer_id)
        if record.source_task_id is not None
        else None
    )
    blockers, selected = _assembly_gate_blockers(record, parent)
    if blockers:
        return "blocked", NetworkAssemblyGateProjection(state="blocked", blockers=blockers)
    if parent is None:
        return "blocked", NetworkAssemblyGateProjection(
            state="blocked", blockers=[NetworkAssemblyGateBlocker(code="broken_parent_link")]
        )
    plan = _build_assembly_plan(record, parent, selected)
    expected_ids = tuple(item.adjudication_id for item in record.adjudications)
    state, persisted = repo.seal_assembly_plan(task_id, reviewer_id, expected_ids, plan)
    return state, persisted


_CONSUMPTION_RECORD_LIMIT_ENV = "QIYAN_CONSUMPTION_RECORD_LIMIT"
_DEFAULT_CONSUMPTION_RECORD_LIMIT = 1000
_JSON_PREVIEW_BOUNDARIES = [
    "JSON 后端仅支持同进程、同实例 writer（preview 语义），不保证跨进程 exactly-once。",
    "多进程 writer 必须切换到 SQLite 后端。",
]


def _consumption_record_limit() -> int:
    """D8 capacity guard: per-task consumption record limit from env."""
    raw = os.environ.get(_CONSUMPTION_RECORD_LIMIT_ENV)
    if raw is None:
        return _DEFAULT_CONSUMPTION_RECORD_LIMIT
    try:
        parsed = int(raw)
    except ValueError:
        return _DEFAULT_CONSUMPTION_RECORD_LIMIT
    return parsed if parsed >= 1 else _DEFAULT_CONSUMPTION_RECORD_LIMIT


def _state_backend_fidelity() -> tuple[str, list[str]]:
    backend = os.environ.get("QIYAN_STATE_BACKEND", "json")
    if backend == "json":
        return "preview", list(_JSON_PREVIEW_BOUNDARIES)
    return "production", []


def _consumption_projection(
    record: NetworkAssemblyConsumptionRecord,
) -> NetworkAssemblyConsumptionProjection:
    return NetworkAssemblyConsumptionProjection(
        consumption_id=record.consumption_id,
        plan_id=record.plan_id,
        plan_sequence=record.plan_sequence,
        canonical_plan_input_sha256=record.canonical_plan_input_sha256,
        output_id=record.output_id,
        output_sha256=record.output_sha256,
        writer_id=record.writer_id,
        consumed_at=record.consumed_at,
    )


_DISEASE_SCOPE_LABELS: dict[str, str] = {"atopic_dermatitis": "Atopic dermatitis"}

_ASSEMBLY_HERB_FORMULA_WARNING = (
    "冻结协议与装配计划不携带药材/复方信息，装配链的 herb/formula 层诚实留空。"
)
_ASSEMBLY_ENRICHMENT_WARNING = (
    "装配切片不执行富集分析（研究者拍板：既有 mock 超几何结果不构成科研结论）。"
)


def _normalize_assembly_score(row: NetworkTargetLineageRow) -> float:
    """Clamp a frozen lineage row score into the chain score domain [0, 1].

    ChEMBL verified rows carry the raw pChEMBL value in ``source_score``; the
    /10 normalization mirrors ``network_connectors._pchembl_to_score`` so the
    assembled chain keeps the same 0-1口径 as provider-derived chains.
    """
    if row.source_score is None:
        return 0.0
    if row.score_name == "pchembl_value":
        return max(0.0, min(row.source_score / 10, 1.0))
    return max(0.0, min(row.source_score, 1.0))


def _assemble_chains_from_plan(
    record: NetworkTaskRecord,
    plan: NetworkAssemblyPlan,
) -> tuple[list[NetworkChain], list[str]]:
    """Deterministically derive compound×target chains from a sealed plan (2026-09-11 拍板).

    One chain per (compound lineage row × selected intersection symbol); rows
    of the same canonical symbol are never merged. Selected rows must resolve
    against the frozen lineage (hash-bound by the plan) — an unresolvable id is
    a persisted-state contradiction and raises for the integrity bucket.
    """
    result = record.result
    if result is None or record.research_protocol is None:
        raise ValueError("assembly input is missing the task result or protocol")
    lineage = result.target_lineage
    disease_rows = {
        row.lineage_row_id: row for row in lineage.disease_targets if row.lineage_row_id is not None
    }
    compound_rows = {
        row.lineage_row_id: row
        for row in lineage.compound_targets
        if row.lineage_row_id is not None
    }
    pathway_by_symbol: dict[str, str] = {}
    for pathway in _load_kegg_pathways():
        if not isinstance(pathway, dict):
            continue
        name = str(pathway.get("name") or "")
        genes = pathway.get("genes")
        if not name or not isinstance(genes, list):
            continue
        for gene in genes:
            pathway_by_symbol.setdefault(str(gene), name)

    disease_label = _DISEASE_SCOPE_LABELS.get(
        record.research_protocol.disease, record.research_protocol.disease
    )

    def _resolve_selection(
        selection: NetworkAssemblySelectedIntersection,
    ) -> tuple[list[NetworkTargetLineageRow], list[NetworkTargetLineageRow]]:
        """Resolve + validate one selection's backing rows against the frozen lineage."""
        try:
            disease = [
                disease_rows[row_id] for row_id in selection.selected_disease_lineage_row_ids
            ]
            compound = [
                compound_rows[row_id] for row_id in selection.selected_compound_lineage_row_ids
            ]
        except KeyError as exc:
            raise ValueError(
                f"selected lineage row cannot be resolved for {selection.lineage_row_id}: {exc}"
            ) from exc
        for row in compound:
            if row.canonical_symbol != selection.canonical_symbol:
                raise ValueError(
                    f"compound lineage row {row.lineage_row_id} does not match "
                    f"selected symbol {selection.canonical_symbol}"
                )
        return disease, compound

    resolved = [
        (selection, *_resolve_selection(selection)) for selection in plan.selected_intersections
    ]
    # 防御分支：mock 行无法通过装配门禁（双侧 verified provenance 才可 seal），
    # 但任何 mock 行都把整批装配链压回 mock 档，宁低不高。
    uses_mock_rows = any(
        row.evidence_origin == "mock"
        for _, disease, compound in resolved
        for row in [*disease, *compound]
    )
    chains: list[NetworkChain] = []
    missing_pathway_count = 0
    for selection, _disease, compound in resolved:
        for compound_row in compound:
            pathway = pathway_by_symbol.get(selection.canonical_symbol, "")
            if not pathway:
                missing_pathway_count += 1
            chains.append(
                NetworkChain(
                    herb="",
                    formula=None,
                    compound=compound_row.raw_identifier,
                    target=selection.canonical_symbol,
                    pathway=pathway,
                    disease=disease_label,
                    score=_normalize_assembly_score(compound_row),
                    related_entity_ids=[
                        selection.lineage_row_id,
                        *selection.selected_disease_lineage_row_ids,
                        compound_row.lineage_row_id or "",
                    ],
                    evidence_refs=[],
                    # 拍板规则 2（宁低不高）：ChEMBL known_activity 行也不上浮 experimental，
                    # 无文献引用的装配链一律压为 predicted；mock 行保持 mock 档。
                    target_evidence_type="mock" if uses_mock_rows else "predicted",
                )
            )
    # 证据分级按行 provenance 而非任务 data_mode：verified 导入任务的 data_mode 只是
    # provider 开关（默认仍为 mock），行的真实性由封存快照决定；mock 行走 ADR-0015
    # 原口径恒 mock_inferred。
    graded = grade_chains_evidence(
        chains,
        data_mode="live" if not uses_mock_rows else record.data_mode,
    )
    warnings = [_ASSEMBLY_HERB_FORMULA_WARNING, _ASSEMBLY_ENRICHMENT_WARNING]
    if missing_pathway_count:
        warnings.append(
            f"{missing_pathway_count}/{len(graded)} 条装配链未命中本地通路字典，pathway 留空。"
        )
    return graded, warnings


def _build_assembly_output(
    record: NetworkTaskRecord,
    plan: NetworkAssemblyPlan,
    request: NetworkAssemblyConsumeRequest,
    output_sha256: str,
    consumed_at: str,
    chains: list[NetworkChain],
    warnings: list[str],
) -> NetworkAssemblyOutput:
    output_id = "assembly-output-" + canonical_json_sha256(
        {
            "task_id": record.task_id,
            "source_task_id": record.source_task_id,
            "plan_id": plan.plan_id,
            "plan_sequence": plan.plan_sequence,
            "canonical_plan_input_sha256": plan.canonical_plan_input_sha256,
            "output_sha256": output_sha256,
        }
    )
    return NetworkAssemblyOutput(
        output_id=output_id,
        task_id=record.task_id,
        source_task_id=record.source_task_id or "",
        plan_id=plan.plan_id,
        plan_sequence=plan.plan_sequence,
        canonical_plan_input_sha256=plan.canonical_plan_input_sha256,
        output_sha256=output_sha256,
        writer_id=request.writer_id,
        consumed_at=consumed_at,
        chains=chains,
        warnings=warnings,
        disclaimer=DISCLAIMER,
    )


def _build_consumption_record(
    record: NetworkTaskRecord,
    plan: NetworkAssemblyPlan,
    output: NetworkAssemblyOutput,
    consumed_at: str,
) -> NetworkAssemblyConsumptionRecord:
    consumption_id = "assembly-consumption-" + canonical_json_sha256(
        {
            "task_id": record.task_id,
            "plan_id": plan.plan_id,
            "output_id": output.output_id,
            "consumed_at": consumed_at,
            "nonce": uuid4().hex,
        }
    )
    return NetworkAssemblyConsumptionRecord(
        consumption_id=consumption_id,
        task_id=record.task_id,
        owner_id=record.owner_id or "",
        plan_id=plan.plan_id,
        plan_sequence=plan.plan_sequence,
        canonical_plan_input_sha256=plan.canonical_plan_input_sha256,
        output_id=output.output_id,
        output_sha256=output.output_sha256,
        writer_id=output.writer_id,
        consumed_at=consumed_at,
    )


def consume_network_assembly_plan(
    task_id: str,
    plan_id: str,
    reviewer_id: str,
    request: NetworkAssemblyConsumeRequest,
) -> tuple[str, NetworkAssemblyConsumeAccepted | list[str] | None]:
    """Writer consumption primitive: atomic write-time validation + exactly-once consume.

    Service pre-checks run in the contract's deterministic failure-code
    priority (D3: 404 → 422 → R3 → R4 → R6 → R7 → 500 integrity); the
    repository primitive then re-validates the mutable channels inside the
    same critical section that appends the output and the consumption record,
    so there is never a check-then-write gap.
    """
    repo = _get_repository()
    record = repo.get_owned(task_id, reviewer_id)
    if record is None:
        return "not_found", None
    plan = repo.get_assembly_plan(task_id, reviewer_id, plan_id)
    if plan is None:
        return "not_found", None
    # 422: a presented plan-input hash that contradicts the stored plan is a
    # malformed (or forged) writer request.
    if (
        request.canonical_plan_input_sha256 is not None
        and request.canonical_plan_input_sha256 != plan.canonical_plan_input_sha256
    ):
        return "invalid_request", ["canonical_plan_input_sha256_mismatch"]
    # R3 pre-check: an already-consumed plan is reported first (D3), whatever
    # happened to the revision afterwards; the repository turns a matching
    # writer + output hash into an idempotent ``existing`` replay.
    plan_consumption = next(
        (
            item
            for item in repo.list_assembly_consumptions(task_id, reviewer_id)
            if item.plan_id == plan_id
        ),
        None,
    )
    if plan_consumption is None:
        # R4 pre-check: the plan must still be the latest revision.
        plans = repo.list_assembly_plans(task_id, reviewer_id)
        latest_sequence = max(item.plan_sequence for item in plans) if plans else 0
        if plan.plan_sequence != latest_sequence:
            return "superseded", None
        # R6 pre-check: recompute the latest-wins adjudication snapshot
        # against the plan binding. The repository re-checks the read-to-lock
        # gap atomically.
        if canonical_json_sha256(_adjudication_latest_snapshot(record)) != (
            plan.adjudication_selection_sha256
        ):
            return "conflict", None
    # R7: parent link must still resolve to a completed root task (409).
    parent = (
        repo.get_owned(record.source_task_id, reviewer_id)
        if record.source_task_id is not None
        else None
    )
    if parent is None or parent.source_task_id is not None or parent.status != "completed":
        return "broken_parent_link", None
    # 500 bucket: persisted-state contradictions, reported with every failed
    # check (R9 plan self-consistency, R1 contradiction, R5/R8 lineage and
    # protocol bindings).
    failed_checks: list[str] = []
    if plan.plan_id != f"assembly-plan-{plan.canonical_plan_input_sha256}":
        failed_checks.append("plan_id_derivation")
    if plan.assembly_input_ready is not True:
        failed_checks.append("assembly_input_ready")
    if plan.formal_network_ready is not False:
        failed_checks.append("formal_network_ready")
    if record.status != "completed" or record.result is None:
        failed_checks.append("task_not_completed")
    if failed_checks:
        return "integrity_failed", failed_checks
    if record.result is not None:
        lineage_hash = canonical_json_sha256(record.result.target_lineage.model_dump(mode="json"))
        if lineage_hash != plan.target_lineage_sha256:
            failed_checks.append("target_lineage_binding")
    if parent.research_protocol is None or record.research_protocol is None:
        failed_checks.append("protocol_missing")
    else:
        parent_protocol_hash = canonical_json_sha256(
            parent.research_protocol.model_dump(mode="json")
        )
        child_protocol_hash = canonical_json_sha256(
            record.research_protocol.model_dump(mode="json")
        )
        if parent_protocol_hash != plan.parent_protocol_sha256:
            failed_checks.append("parent_protocol_binding")
        if child_protocol_hash != plan.child_protocol_sha256:
            failed_checks.append("child_protocol_binding")
    if failed_checks:
        return "integrity_failed", failed_checks
    output_sha256 = canonical_json_sha256(request.output_payload)
    consumed_at = _now_iso()
    try:
        chains, assembly_warnings = _assemble_chains_from_plan(record, plan)
    except ValueError:
        # Selected rows are hash-bound to the frozen lineage; an unresolvable
        # row here is a persisted-state contradiction (500 integrity bucket).
        return "integrity_failed", ["assembly_input_unresolvable"]
    output = _build_assembly_output(
        record, plan, request, output_sha256, consumed_at, chains, assembly_warnings
    )
    consumption = _build_consumption_record(record, plan, output, consumed_at)
    current_adjudication_ids = tuple(item.adjudication_id for item in record.adjudications)
    state, stored_output, stored_consumption = repo.consume_assembly_plan(
        task_id,
        reviewer_id,
        request.writer_id,
        plan_id,
        current_adjudication_ids,
        output,
        consumption,
        _consumption_record_limit(),
    )
    if state not in {"created", "existing"} or stored_output is None or stored_consumption is None:
        return state, None
    fidelity, boundaries = _state_backend_fidelity()
    accepted = NetworkAssemblyConsumeAccepted(
        state="created" if state == "created" else "existing",
        backend_fidelity="preview" if fidelity == "preview" else "production",
        output=stored_output,
        consumption=_consumption_projection(stored_consumption),
        preview_boundaries=boundaries,
    )
    return state, accepted


def build_network_assembly_plan_audit_view(
    task_id: str,
    plan_id: str,
    reviewer_id: str,
) -> NetworkAssemblyPlanAuditView | None:
    """D6 read-only audit projection: readable is not consumable."""
    repo = _get_repository()
    record = repo.get_owned(task_id, reviewer_id)
    if record is None:
        return None
    plan = repo.get_assembly_plan(task_id, reviewer_id, plan_id)
    if plan is None:
        return None
    plans = repo.list_assembly_plans(task_id, reviewer_id)
    latest = max(plans, key=lambda item: item.plan_sequence) if plans else None
    consumptions = {
        item.plan_id: item for item in repo.list_assembly_consumptions(task_id, reviewer_id)
    }
    consumption = consumptions.get(plan.plan_id)
    is_latest = latest is not None and latest.plan_id == plan.plan_id
    return NetworkAssemblyPlanAuditView(
        plan=plan,
        is_latest_plan=is_latest,
        is_consumed=consumption is not None,
        is_superseded_by=None if is_latest or latest is None else latest.plan_id,
        consumption=(_consumption_projection(consumption) if consumption is not None else None),
    )


def _build_adjudication_id(
    task_id: str,
    lineage_row_id: str,
    decision: ManualAdjudicationDecision,
    decided_at: str,
    sequence: int,
    nonce: str,
) -> str:
    """Derive the audit id for one adjudication event.

    ``sequence`` comes from a pre-write snapshot, so two concurrent submissions of
    the same decision on the same row can observe the same value; ``nonce`` keeps
    the id unique per event so it stays a stable handle into the audit trail.
    """
    identity_payload = {
        "task_id": task_id,
        "lineage_row_id": lineage_row_id,
        "decision": decision,
        "decided_at": decided_at,
        "sequence": sequence,
        "nonce": nonce,
    }
    return f"adjudication-{_canonical_sha256(identity_payload)}"


def submit_network_target_adjudication(
    task_id: str,
    reviewer_id: str,
    request: NetworkAdjudicationRequest,
) -> tuple[str, NetworkTargetAdjudicationRecord | None]:
    """Append one manual adjudication to a frozen completed task.

    Fail closed: unknown/foreign/legacy-ownerless tasks are ``not_found``;
    only a ``completed`` task with a frozen result may be adjudicated;
    ``lineage_row_id`` must exist in the frozen target lineage.  The
    reviewer identity is persisted for audit but never projected back.
    """
    repo = _get_repository()
    record = repo.get_owned(task_id, reviewer_id)
    if record is None:
        return "not_found", None
    if record.status != "completed" or record.result is None:
        return "not_completed", None
    if request.lineage_row_id not in _lineage_row_ids(record.result):
        return "unknown_row", None
    omics_fields: dict[str, Any] = {}
    if request.decision == "omics_confirmed":
        assert request.omics is not None  # guaranteed by the request validator
        state, omics_fields = _verify_omics_confirmation(
            record, request.lineage_row_id, request.omics
        )
        if state != "ok":
            return state, None
    decided_at = _now_iso()
    adjudication = NetworkTargetAdjudication(
        adjudication_id=_build_adjudication_id(
            task_id,
            request.lineage_row_id,
            request.decision,
            decided_at,
            len(record.adjudications),
            uuid4().hex,
        ),
        lineage_row_id=request.lineage_row_id,
        decision=request.decision,
        reason=request.reason,
        decided_at=decided_at,
        reviewer_id=reviewer_id,
        **omics_fields,
    )
    updated = repo.append_adjudication(task_id, reviewer_id, adjudication)
    if updated is None:
        return "not_found", None
    return "ok", NetworkTargetAdjudicationRecord(
        adjudication_id=adjudication.adjudication_id,
        lineage_row_id=adjudication.lineage_row_id,
        decision=adjudication.decision,
        reason=adjudication.reason,
        decided_at=adjudication.decided_at,
        omics_accession=adjudication.omics_accession,
        omics_canonical_symbol=adjudication.omics_canonical_symbol,
        omics_log2fc=adjudication.omics_log2fc,
        omics_adj_p_value=adjudication.omics_adj_p_value,
    )


def _verify_omics_confirmation(
    record: NetworkTaskRecord,
    lineage_row_id: str,
    context: OmicsAdjudicationContext,
) -> tuple[str, dict[str, Any]]:
    """Re-verify every machine omics condition at adjudication time (ADR-0018
    Gate 3). The 6th condition — the human confirmation — is the request
    itself. Returns (state, sealed_fields); state is "ok" only when all
    machine conditions hold against the frozen snapshot, freshly recomputed.
    """
    result = record.result
    assert result is not None
    disease_row = next(
        (
            row
            for row in result.target_lineage.disease_targets
            if row.lineage_row_id == lineage_row_id
        ),
        None,
    )
    if disease_row is None or disease_row.canonical_symbol != context.canonical_symbol:
        return "omics_row_symbol_mismatch", {}
    try:
        projection = compute_omics_deg_projection(result, accession=context.accession)
    except OmicsSnapshotConflictError:
        return "omics_snapshot_missing", {}
    except (OmicsVerificationBlockedError, ValueError):
        return "omics_unverified", {}
    candidate = next(
        (
            item
            for item in projection.candidates
            if item.canonical_symbol == context.canonical_symbol
        ),
        None,
    )
    # Candidate presence already implies the frozen thresholds hold and the
    # dataset conditions (Homo sapiens + atopic dermatitis) matched; the row
    # binding check proves this task's frozen lineage backs the edge.
    if candidate is None or lineage_row_id not in candidate.lineage_row_ids:
        return "omics_not_confirmed", {}
    return "ok", {
        "omics_accession": context.accession,
        "omics_canonical_symbol": context.canonical_symbol,
        "omics_log2fc": candidate.log2fc,
        "omics_adj_p_value": candidate.adj_p_value,
    }


def _has_unlinked_compound_child(record: NetworkTaskRecord) -> bool:
    return record.compound_target_import is not None and record.source_task_id is None


def _unlinked_compound_child_response(record: NetworkTaskRecord) -> NetworkResultResponse:
    """Project legacy unlinked children as failed without mutating a GET read."""
    return NetworkResultResponse(
        task_id=record.task_id,
        status="failed",
        progress=100,
        data_mode=record.data_mode,
        result=None,
        error=_UNLINKED_COMPOUND_CHILD_ERROR,
        warnings=[_UNLINKED_COMPOUND_CHILD_ERROR],
    )


def get_network_analysis_result(
    task_id: str,
    reviewer_id: str = "local-preview",
) -> tuple[str, NetworkResultResponse | None]:
    repo = _get_repository()
    current = repo.get_owned(task_id, reviewer_id)
    if current is None:
        return "not_found", None
    if _has_unlinked_compound_child(current):
        return "ok", _unlinked_compound_child_response(current)
    if current.status in {"completed", "failed"}:
        return "ok", _result_response(current)
    record = repo.advance(task_id, reviewer_id, _advance_record)
    if record is None:
        return "not_found", None
    return "ok", _result_response(record)


def get_network_analysis_task(
    task_id: str,
    reviewer_id: str = "local-preview",
) -> tuple[str, NetworkResultResponse | None]:
    """Read an owner-scoped task without advancing its state machine."""
    record = _get_repository().get_owned(task_id, reviewer_id)
    if record is None:
        return "not_found", None
    if _has_unlinked_compound_child(record):
        return "ok", _unlinked_compound_child_response(record)
    return "ok", _result_response(record)


def _task_summary(record: NetworkTaskRecord) -> NetworkTaskSummary:
    """Project a record to its list summary; owner_id is intentionally dropped."""
    status: TaskStatus = "failed" if _has_unlinked_compound_child(record) else record.status
    formal_network_ready = (
        record.result.readiness.formal_network_ready if record.result is not None else False
    )
    return NetworkTaskSummary(
        task_id=record.task_id,
        source_task_id=record.source_task_id,
        query=record.query,
        analysis_type=record.analysis_type,
        status=status,
        data_mode=record.data_mode,
        formal_network_ready=formal_network_ready,
        created_at=record.created_at,
    )


def list_network_analysis_tasks(reviewer_id: str = "local-preview") -> NetworkTaskListResponse:
    """List owner-scoped task summaries without advancing any state machine.

    Legacy ownerless records are excluded at the repository layer (fail
    closed); legacy unlinked compound children are projected as failed,
    matching the read-only result/report projection.
    """
    records = _get_repository().list_records_for_owner(reviewer_id)
    return NetworkTaskListResponse(tasks=[_task_summary(record) for record in records])


def list_all_entities(
    entity_repo: NetworkEntityRepository | None = None,
) -> NetworkEntitiesResponse:
    repo = entity_repo or NetworkEntityRepository()
    return NetworkEntitiesResponse(
        herbs=repo.list_herbs(),
        formulas=repo.list_formulas(),
        compounds=repo.list_compounds(),
        targets=repo.list_targets(),
        pathways=repo.list_pathways(),
    )


def _escape_table_cell(value: str | int | float | None) -> str:
    """Escape a value for use in a Markdown table cell.

    - None / empty string → "无"
    - HTML and Markdown control characters are rendered as literal text
    - Whitespace collapsed to single space
    """
    if value is None or value == "":
        return "无"
    text = str(value)
    text = " ".join(text.split())
    for character in r"\\`*[]()|":
        text = text.replace(character, f"\\{character}")
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace("://", "&#58;//")
    return text


def _append_target_lineage_table(lines: list[str], rows: list[NetworkTargetLineageRow]) -> None:
    lines.append(
        "| Lineage row ID | Raw ID | Canonical | Source | Version | Source query | Query date | Retrieved at | Species | Score field | Score | Threshold rule | Mapping | Mapping version | Evidence | Auto | Adjudication | Decision | Source record IDs |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---:|---|---|---|---|---|---|---|---|")
    for row in rows:
        threshold_rule = (
            f"{row.threshold_operator} {row.applied_threshold}"
            if row.threshold_operator is not None and row.applied_threshold is not None
            else None
        )
        cells: list[str | int | float | None] = [
            row.lineage_row_id,
            row.raw_identifier,
            row.canonical_symbol,
            row.source_database,
            row.database_version,
            row.source_query,
            row.query_date.isoformat(),
            row.retrieved_at,
            row.species,
            row.score_name,
            row.source_score,
            threshold_rule,
            row.identifier_mapping,
            row.identifier_mapping_version,
            row.evidence_origin,
            row.automatic_status,
            row.adjudication_status,
            row.decision,
            ", ".join(row.source_record_ids),
        ]
        lines.append(f"| {' | '.join(_escape_table_cell(cell) for cell in cells)} |")


def _format_score(score: float) -> str:
    """Format a 0-1 score as a percentage string like '85%'."""
    return f"{int(round(score * 100))}%"


def _format_entity_ids(ids: list[str]) -> str:
    """Format a list of entity IDs as a comma-separated string, or '无' if empty."""
    return ", ".join(ids) if ids else "无"


def _analysis_type_label(analysis_type: AnalysisType) -> str:
    """Return the Chinese display label for an analysis type."""
    return "单味中药" if analysis_type == "herb" else "复方"


def _target_evidence_type_label(value: str) -> str:
    if value == "known_activity":
        return "已知活性证据"
    if value == "predicted":
        return "预测靶点"
    if value == "mixed":
        return "已知+预测"
    return "Mock"


# ── Evidence grading (ADR-0015) ─────────────────────────────
# A mechanism chain's trustworthiness is bounded by its weakest provenance
# link, so mock chains are hard-pinned to the lowest level. Deterministic:
# no randomness, no external calls, no probability/efficacy estimate.
_EVIDENCE_LEVEL_ORDER: list[EvidenceLevel] = [
    "experimental",
    "omics_validated",
    "literature_supported",
    "predicted",
    "mock_inferred",
]
_EVIDENCE_LEVEL_LABELS: dict[EvidenceLevel, str] = {
    "experimental": "实验证据",
    "omics_validated": "组学验证",
    "literature_supported": "文献支撑",
    "predicted": "预测证据",
    "mock_inferred": "演示推断（未验证）",
}


def derive_chain_evidence_level(chain: NetworkChain, *, data_mode: DataMode) -> EvidenceLevel:
    """Deterministically grade one chain's evidence support (ADR-0015)."""
    # Honesty invariant: mock data can never claim real evidence strength.
    if data_mode != "live":
        return "mock_inferred"
    if chain.target_evidence_type == "known_activity":
        return "experimental"
    if chain.target_evidence_type == "mixed" or chain.evidence_refs:
        return "literature_supported"
    # Live but only predicted / unresolved targets: weakest live tier.
    return "predicted"


def grade_chains_evidence(chains: list[NetworkChain], *, data_mode: DataMode) -> list[NetworkChain]:
    """Return new chains with ``evidence_level`` filled (immutable copy)."""
    return [
        chain.model_copy(
            update={"evidence_level": derive_chain_evidence_level(chain, data_mode=data_mode)}
        )
        for chain in chains
    ]


def _evidence_level_label(level: EvidenceLevel | None) -> str:
    return _EVIDENCE_LEVEL_LABELS.get(level or "mock_inferred", "演示推断（未验证）")


def build_network_report_markdown(
    result: NetworkAnalysisResult,
    exported_at: str | None = None,
    adjudication: NetworkAdjudicationSummary | None = None,
    assembly_gate: NetworkAssemblyGateProjection | None = None,
) -> str:
    """Build a Markdown report string equivalent to the frontend
    ``buildNetworkReportMarkdown`` function.

    The output format is strictly aligned with
    ``frontend/lib/network-report-export.ts``.
    """
    adjudication = adjudication or NetworkAdjudicationSummary()
    assembly_gate = assembly_gate or NetworkAssemblyGateProjection()
    has_compound_provenance = result.target_lineage.compound_import_provenance is not None
    if has_compound_provenance and result.source_task_id is None:
        raise ValueError("compound target lineage is missing its immutable source task link")
    if result.source_task_id is not None and not has_compound_provenance:
        raise ValueError("source_task_id is only valid for compound target lineage")
    if has_compound_provenance and (
        result.chains
        or result.enrichment is not None
        or result.ppi_edges
        or result.data_sources
        or result.pipeline_steps
    ):
        raise ValueError("compound target lineage must remain a snapshot-only output")
    timestamp = exported_at or datetime.now(UTC).isoformat()
    lines: list[str] = []
    is_imported_compound_snapshot = result.source_task_id is not None

    # ── Header ──────────────────────────────────────────────
    lines.append("# Qiyan Nexus 网络药理学报告导出")
    lines.append("")
    lines.append(f"- 导出时间（UTC）：{timestamp}")
    lines.append(f"- task_id：{result.task_id}")
    if result.source_task_id is not None:
        lines.append(f"- 来源疾病任务：{_escape_table_cell(result.source_task_id)}")
    lines.append(f"- 分析对象：{_escape_table_cell(result.query)}")
    lines.append(f"- 分析类型：{_analysis_type_label(result.analysis_type)}")
    lines.append(f"- 数据模式：{result.data_mode}")
    lines.append(f"- 链路数量：{len(result.chains)}")
    if is_imported_compound_snapshot:
        lines.append("- 数据来源：服务端核验的疾病/成分靶点快照，尚未生成可复算网络或通路结果")
    elif result.data_mode == "live":
        lines.append("- 数据来源：显式 opt-in 真实数据链路（含缓存/导入来源）")
    else:
        lines.append("- 数据来源：本报告基于本地 mock seed graph 生成")
    lines.append("")
    if is_imported_compound_snapshot:
        lines.append(
            "> **数据说明**：当前仅导出不可变靶点 lineage 和服务端派生交集；"
            "未调用 provider 生成机制链、富集、PPI 或通路，不能把快照一致性解释为网络结论。"
        )
    elif result.data_mode == "live":
        lines.append(
            "> **数据说明**：本报告来自显式启用的真实数据链路；仍需核对外部数据库版本、"
            "缓存时间、授权边界与原始记录，不可直接作为临床决策结论。"
        )
    else:
        lines.append(
            "> **数据说明**：本报告基于本地演示数据生成，仅用于功能验证与评审走查；"
            "不可作为科研发表、临床决策或真实数据库分析结果。"
        )
    lines.append("")

    lines.append("## 研究协议与科研门禁")
    lines.append("")
    if result.research_protocol is None:
        lines.append("- 研究协议：缺失（legacy 或不可审计任务）")
    else:
        lines.append(f"- 疾病范围：{result.research_protocol.disease}")
        lines.append(f"- 明确表型：{_escape_table_cell(result.research_protocol.phenotype)}")
        lines.append(f"- 物种：{result.research_protocol.species}")
        lines.append(f"- 证据策略：{result.research_protocol.evidence_policy}")
        lines.append(f"- 查询日期：{result.research_protocol.query_date.isoformat()}")
    lines.append(f"- protocol_complete：{'是' if result.readiness.protocol_complete else '否'}")
    lines.append(
        f"- formal_network_ready：{'是' if result.readiness.formal_network_ready else '否'}"
    )
    if result.readiness.blocking_reasons:
        lines.append("- 阻塞项：")
        for reason in result.readiness.blocking_reasons:
            lines.append(f"  - {_escape_table_cell(reason)}")
    lines.append("")

    lines.append("## 候选装配输入门禁")
    lines.append("")
    lines.append(f"- Policy：{assembly_gate.policy_id}")
    lines.append(f"- 状态：{assembly_gate.state}")
    lines.append("- formal_network_ready：否")
    lines.append(
        "> 候选计划只封存协议、双侧 artifact、冻结 lineage 与判定快照；"
        "不生成网络边，不授权后续 writer，也不表示科研就绪。"
    )
    if assembly_gate.blockers:
        lines.append("- 阻塞项：")
        for blocker in assembly_gate.blockers:
            row_suffix = f"（{len(blocker.row_ids)} 行）" if blocker.row_ids else ""
            lines.append(f"  - {blocker.code}{row_suffix}")
    if assembly_gate.latest_plan is not None:
        lines.append(f"- 最新计划：{assembly_gate.latest_plan.plan_id}")
        lines.append(f"- 纳入交集：{assembly_gate.latest_plan.selected_intersection_count}")
        lines.append(
            f"- Plan input SHA-256：{assembly_gate.latest_plan.canonical_plan_input_sha256}"
        )
        lines.append(
            "- 消费状态：已被 writer 消费（审计记录见消费流）"
            if assembly_gate.latest_plan.is_consumed
            else "- 消费状态：尚未被消费"
        )
    lines.append("")

    lines.append("## 靶点集合与逐行 Lineage")
    lines.append("")
    lines.append(f"- 观察单元汇总：{result.target_lineage.observation_unit}")
    lines.append(
        f"- 疾病/成分观察单元：{result.target_lineage.disease_observation_unit} / "
        f"{result.target_lineage.compound_observation_unit}"
    )
    lines.append(f"- 交集观察单元：{result.target_lineage.intersection_observation_unit}")
    lines.append(
        f"- 疾病靶点：{result.target_lineage.disease_target_count}（lineage rows: {result.target_lineage.disease_lineage_row_count}）"
    )
    lines.append(
        f"- 成分靶点：{result.target_lineage.compound_target_count}（lineage rows: {result.target_lineage.compound_lineage_row_count}）"
    )
    lines.append(
        f"- 派生候选交集：{result.target_lineage.intersection_target_count}（derivation rows: {result.target_lineage.intersection_lineage_row_count}）"
    )
    for warning in result.target_lineage.warnings:
        lines.append(f"- 警告：{_escape_table_cell(warning)}")
    lines.append("")

    lines.append("### 疾病导入来源")
    lines.append("")
    provenance = result.target_lineage.disease_import_provenance
    if provenance is None:
        lines.append("（未提供疾病靶点导入 artifact。）")
    else:
        lines.append(f"- Source profile：{_escape_table_cell(provenance.source_profile)}")
        lines.append(
            f"- Source database/version：{_escape_table_cell(provenance.source_database)} / "
            f"{_escape_table_cell(provenance.database_version)}"
        )
        lines.append(
            f"- Source query：{_escape_table_cell(provenance.source_query_id)} / "
            f"{_escape_table_cell(provenance.source_query_label)}"
        )
        lines.append(
            "- Source query parameters："
            + _escape_table_cell(
                json.dumps(
                    provenance.source_query_parameters,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        )
        lines.append(f"- Retrieved at：{_escape_table_cell(provenance.retrieved_at.isoformat())}")
        lines.append(
            f"- Score/threshold：{provenance.score_name} {provenance.threshold_operator} "
            f"{provenance.applied_threshold}"
        )
        lines.append(
            f"- Identifier mapping/version：{_escape_table_cell(provenance.identifier_mapping)} / "
            f"{_escape_table_cell(provenance.identifier_mapping_version)}"
        )
        lines.append(f"- Imported source records：{provenance.record_count}")
        lines.append(f"- Provenance verification：{provenance.provenance_verification_status}")
        lines.append(f"- Import payload SHA-256：{provenance.import_payload_sha256}")
        if provenance.provenance_verification_status == "server_verified_raw_artifact":
            lines.append(f"- Source artifact SHA-256：{provenance.source_artifact_sha256}")
            lines.append(
                "- Submitted artifact filename (untrusted label)："
                f"{_escape_table_cell(provenance.source_artifact_filename)}"
            )
            lines.append(
                "- Submitted artifact media type (untrusted label)："
                f"{_escape_table_cell(provenance.source_artifact_media_type)}"
            )
            lines.append(
                f"- Usage/license note：{_escape_table_cell(provenance.usage_license_note)}"
            )
            lines.append(
                "> **验证边界**：source artifact 哈希只证明原始文件字节完整性与服务端解析一致性；"
                "filename/media type 是客户端传输标签且不受 manifest 绑定；不证明 release 选择正确，"
                "不证明表型映射正确，也不证明靶点有生物学意义。"
            )
        else:
            lines.append(
                "> **验证边界**：payload 哈希只证明导入内容完整性，不证明外部数据库真实性；"
                "该来源仍需服务端 connector 或原始快照核验。"
            )
    lines.append("")

    lines.append("### 成分导入来源")
    lines.append("")
    compound_provenance = result.target_lineage.compound_import_provenance
    if compound_provenance is None:
        lines.append("（未提供服务端核验的成分靶点原始 artifact。）")
    else:
        lines.append(f"- Source profile：{_escape_table_cell(compound_provenance.source_profile)}")
        lines.append(
            f"- Compound：{_escape_table_cell(compound_provenance.compound_id)} / "
            f"{_escape_table_cell(compound_provenance.compound_label)}"
        )
        lines.append(
            f"- Source database/version：{_escape_table_cell(compound_provenance.source_database)} / "
            f"{_escape_table_cell(compound_provenance.database_version)}"
        )
        lines.append(
            f"- Source query：{_escape_table_cell(compound_provenance.source_query_id)} / "
            f"{_escape_table_cell(compound_provenance.source_query_label)}"
        )
        lines.append(
            "- Source query parameters："
            + _escape_table_cell(
                json.dumps(
                    compound_provenance.source_query_parameters.model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        )
        lines.append(
            f"- Retrieved at：{_escape_table_cell(compound_provenance.retrieved_at.isoformat())}"
        )
        lines.append(
            f"- Score/threshold：{compound_provenance.score_name} "
            f"{compound_provenance.threshold_operator} {compound_provenance.applied_threshold}"
        )
        lines.append(
            "- Identifier mapping/version："
            f"{_escape_table_cell(compound_provenance.identifier_mapping)} / "
            f"{_escape_table_cell(compound_provenance.identifier_mapping_version)}"
        )
        lines.append(f"- Imported source records：{compound_provenance.record_count}")
        lines.append(
            f"- Provenance verification：{compound_provenance.provenance_verification_status}"
        )
        lines.append(f"- Import payload SHA-256：{compound_provenance.import_payload_sha256}")
        lines.append(f"- Source artifact SHA-256：{compound_provenance.source_artifact_sha256}")
        lines.append(
            "- Submitted artifact filename (untrusted label)："
            f"{_escape_table_cell(compound_provenance.source_artifact_filename)}"
        )
        lines.append(
            "- Submitted artifact media type (untrusted label)："
            f"{_escape_table_cell(compound_provenance.source_artifact_media_type)}"
        )
        lines.append(
            f"- Usage/license note：{_escape_table_cell(compound_provenance.usage_license_note)}"
        )
        lines.append(
            "> **验证边界**：source artifact 哈希只证明原始文件字节完整性与服务端解析一致性；"
            "filename/media type 是客户端传输标签且不受 manifest 绑定；不证明 release 选择正确，"
            "不证明 target mapping 正确，也不证明 compound-target 边具有生物学意义。"
        )
    lines.append("")

    lines.append("### 疾病靶点集合")
    lines.append("")
    if result.target_lineage.disease_targets:
        _append_target_lineage_table(lines, result.target_lineage.disease_targets)
    elif provenance is not None:
        if provenance.provenance_verification_status == "server_verified_raw_artifact":
            lines.append("（服务端解析的原始 artifact 在声明阈值下零命中。）")
        else:
            lines.append("（客户端导入声明零命中；来源与查询执行尚未由服务端验证。）")
    else:
        lines.append("（未采集独立疾病靶点集合。）")
    lines.append("")

    lines.append("### 成分靶点集合")
    lines.append("")
    if not result.target_lineage.compound_targets:
        lines.append("（未提取成分靶点。）")
    else:
        _append_target_lineage_table(lines, result.target_lineage.compound_targets)
    lines.append("")

    lines.append("### 派生候选交集")
    lines.append("")
    if result.target_lineage.intersection_targets:
        lines.append(
            "| Derivation row ID | Canonical | Derivation | Disease lineage refs | Compound lineage refs | Auto | Adjudication | Decision |"
        )
        lines.append("|---|---|---|---|---|---|---|---|")
        for row in result.target_lineage.intersection_targets:
            cells: list[str | int | float | None] = [
                row.lineage_row_id,
                row.canonical_symbol,
                row.derivation,
                ", ".join(row.disease_lineage_row_ids),
                ", ".join(row.compound_lineage_row_ids),
                row.automatic_status,
                row.adjudication_status,
                row.decision,
            ]
            lines.append(f"| {' | '.join(_escape_table_cell(cell) for cell in cells)} |")
    else:
        lines.append("（没有服务端派生的候选交集；禁止从成分靶点集合自我构造疾病交集。）")
    lines.append("")

    # ── Manual adjudication section (append-only audit data) ──
    lines.append("## 人工判定")
    lines.append("")
    lines.append(
        "> 逐行人工判定是附加审计数据：不改变冻结的靶点 lineage、来源 provenance 或 "
        "formal_network_ready；同一行多次判定时仅展示最新一条。"
    )
    lines.append("")
    lines.append(
        "| Included（纳入） | Excluded（排除） | Needs review（待复核） | Pending（待判定） |"
    )
    lines.append("|---:|---:|---:|---:|")
    lines.append(
        f"| {adjudication.counts.included} | {adjudication.counts.excluded} | "
        f"{adjudication.counts.needs_review} | {adjudication.counts.pending} |"
    )
    lines.append("")
    if not adjudication.current:
        lines.append("（尚无人工判定记录。）")
    else:
        lines.append("| Lineage row ID | 判定 | 理由 | 判定时间（UTC） |")
        lines.append("|---|---|---|---|")
        for entry in adjudication.current:
            adjudication_cells: list[str | int | float | None] = [
                entry.lineage_row_id,
                entry.decision,
                entry.reason,
                entry.decided_at,
            ]
            lines.append(f"| {' | '.join(_escape_table_cell(c) for c in adjudication_cells)} |")
    lines.append("")

    if result.data_mode == "live" and not is_imported_compound_snapshot:
        lines.append("## 数据来源与参数版本")
        lines.append("")
        if result.data_sources:
            lines.append(
                "| Source | Record ID | URL | Retrieved at | Cache | Usage note | Cache key |"
            )
            lines.append("|---|---|---|---|---|---|---|")
            for source in result.data_sources:
                cells = [
                    source.name,
                    source.source_record_id,
                    source.url,
                    source.retrieved_at,
                    "cache" if source.from_cache else "live",
                    source.license_note,
                    source.cache_key,
                ]
                escaped = [_escape_table_cell(c) for c in cells]
                lines.append(f"| {' | '.join(escaped)} |")
        else:
            lines.append("（当前结果未返回外部数据来源元数据。）")
        lines.append("")

        lines.append("## 运行步骤")
        lines.append("")
        if result.pipeline_steps:
            lines.append("| Step | Status | Duration ms | Requests | Cache hits | Warning |")
            lines.append("|---|---|---:|---:|---:|---|")
            for step in result.pipeline_steps:
                pipeline_cells: list[str | int | float | None] = [
                    step.name,
                    step.status,
                    step.duration_ms,
                    step.external_request_count,
                    step.cache_hit_count,
                    step.warning,
                ]
                escaped = [_escape_table_cell(c) for c in pipeline_cells]
                lines.append(f"| {' | '.join(escaped)} |")
        else:
            lines.append("（当前结果未返回运行步骤元数据。）")
        lines.append("")

        if result.warnings:
            lines.append("## 运行警告")
            lines.append("")
            for warning in result.warnings:
                lines.append(f"- {_escape_table_cell(warning)}")
            lines.append("")

    # ── Chains table ────────────────────────────────────────
    lines.append("## 链路结果")
    lines.append("")
    if not result.chains:
        lines.append("（当前报告没有可导出的机制链路。）")
    else:
        if result.data_mode == "live":
            lines.append(
                "| 序号 | 方剂 | 单味中药 | 成分 | 靶点 | 靶点证据类型 | 通路 | 疾病 | 置信度 | Evidence refs |"
            )
            lines.append("|---|---|---|---|---|---|---|---|---:|---|")
        else:
            lines.append(
                "| 序号 | 方剂 | 单味中药 | 成分 | 靶点 | 通路 | 疾病 | Mock 置信度 | 相关实体 ID |"
            )
            lines.append("|---|---|---|---|---|---|---|---:|---|")
        for idx, chain in enumerate(result.chains, start=1):
            if result.data_mode == "live":
                cells = [
                    str(idx),
                    chain.formula,
                    chain.herb,
                    chain.compound,
                    chain.target,
                    _target_evidence_type_label(chain.target_evidence_type),
                    chain.pathway,
                    chain.disease,
                    _format_score(chain.score),
                    _format_entity_ids(chain.evidence_refs),
                ]
            else:
                cells = [
                    str(idx),
                    chain.formula,
                    chain.herb,
                    chain.compound,
                    chain.target,
                    chain.pathway,
                    chain.disease,
                    _format_score(chain.score),
                    _format_entity_ids(chain.related_entity_ids),
                ]
            escaped = [_escape_table_cell(c) for c in cells]
            lines.append(f"| {' | '.join(escaped)} |")
    lines.append("")

    # ── Evidence grading section (ADR-0015) ─────────────────
    lines.append("## 证据分级")
    lines.append("")
    lines.append(
        "> 依据《网络药理学评价方法指南》的可靠性/规范性/可解释性原则，对每条机制链按其"
        "最弱一环的来源给出确定性证据等级（不改变链路排序，不表示概率或疗效）。"
    )
    lines.append("")
    grading_counts: dict[EvidenceLevel, int] = {level: 0 for level in _EVIDENCE_LEVEL_ORDER}
    for graded_chain in result.chains:
        grading_counts[graded_chain.evidence_level or "mock_inferred"] += 1
    lines.append("| 证据等级 | Level | 链路数 |")
    lines.append("|---|---|---:|")
    for level in _EVIDENCE_LEVEL_ORDER:
        lines.append(f"| {_evidence_level_label(level)} | `{level}` | {grading_counts[level]} |")
    lines.append("")
    if result.data_mode != "live":
        lines.append(
            "> **边界**：本报告为 mock 演示数据，所有链路证据等级恒为 `mock_inferred`，"
            "不代表指南意义上的可靠性达标，也不可作为真实证据强度。"
        )
        lines.append("")

    # ── Enrichment section ──────────────────────────────────
    if result.enrichment and result.enrichment.terms:
        lines.append("## 富集分析结果")
        lines.append("")
        lines.append(f"- 输入基因数：{result.enrichment.input_gene_count}")
        lines.append(f"- 背景基因数：{result.enrichment.background_gene_count}")
        lines.append(f"- 分析类型：{result.enrichment.analysis_type}")
        lines.append(f"- 富集通路/功能数：{len(result.enrichment.terms)}")
        lines.append("")
        lines.append(
            "| Term ID | 通路/功能 | 类别 | 重叠基因 | P-value | 校正后 P-value | 基因列表 |"
        )
        lines.append("|---|---|---|---:|---:|---:|---|")
        for term in result.enrichment.terms:
            term_name = term.term_name_zh or term.term_name
            overlap = f"{term.overlap_count}/{term.gene_count}"
            p_val = f"{term.p_value:.2e}"
            adj_p_val = f"{term.adjusted_p_value:.2e}"
            genes = ", ".join(term.genes)
            cells = [
                term.term_id,
                term_name,
                term.category,
                overlap,
                p_val,
                adj_p_val,
                genes,
            ]
            escaped = [_escape_table_cell(c) for c in cells]
            lines.append(f"| {' | '.join(escaped)} |")
        lines.append("")
        lines.append("### 参数说明")
        lines.append("")
        lines.append("- **P-value**：超几何分布计算的原始 p 值")
        lines.append("- **校正后 P-value**：Bonferroni 校正后的 p 值")
        lines.append("- **重叠基因**：输入基因与该通路/功能的交集数量")
        lines.append("- **过滤条件**：p < 0.05 且重叠基因数 >= 2")
        lines.append("")

    # ── Network graph placeholder ───────────────────────────
    lines.append("## 网络图")
    lines.append("")
    if is_imported_compound_snapshot:
        lines.append("（当前仅有冻结靶点快照，尚未构建可复算的成分-靶点-通路网络图。）")
    else:
        lines.append("![成分-靶点-通路网络图](placeholder-network-graph.png)")
        lines.append("")
        lines.append("*注：图片占位符，实际图片生成功能待后续实现*")
    lines.append("")

    # ── Boundary notes ──────────────────────────────────────
    lines.append("## 边界说明")
    lines.append("")
    if is_imported_compound_snapshot:
        lines.append("- 靶点快照工程一致性不证明来源官方性、release/query 选择或生物学意义。")
        lines.append("- 未完成可复算的成分-靶点-通路网络、富集、PPI 或逐边人工 adjudication。")
    elif result.data_mode == "live":
        lines.append("- 本报告来自显式 opt-in 真实数据链路，仍需人工核对外部来源版本与缓存时间。")
        lines.append("- 预测靶点来自本地导入 artifact，不自动爬取 SwissTargetPrediction。")
        lines.append("- TCMSP 入口仅在 operator 明确允许或已有缓存时使用。")
    else:
        lines.append("- 不是正式网络药理学计算。")
        lines.append(
            "- 富集分析基于本地 JSON 字典（mock），不代表真实 KEGG REST API 或 STRING 数据库。"
        )
    lines.append("- 不构成诊断或治疗建议，实际判断需核对原始文献、参数版本与临床背景。")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(result.disclaimer)
    lines.append("")

    return "\n".join(lines)
