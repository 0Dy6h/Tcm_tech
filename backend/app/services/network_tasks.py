"""Task creation and the poll-driven analysis state machine (_advance_record)."""

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.config import get_settings
from app.repositories.network_entities import NetworkEntityRepository
from app.schemas.network import (
    AnalysisType,
    DataMode,
    EvidencePolicy,
    NetworkAnalysisResult,
    NetworkAnalyzeAccepted,
    NetworkAnalyzeRequest,
    NetworkChain,
    NetworkCompoundTargetSnapshot,
    NetworkCompoundTargetVerifyMetadata,
    NetworkDiseaseTargetImport,
    NetworkDiseaseTargetSnapshot,
    NetworkDiseaseTargetVerifyMetadata,
    NetworkResearchProtocol,
    NetworkTaskRecord,
)
from app.schemas.network_entities import Compound, Pathway, Target
from app.services.enrichment import build_enrichment_result
from app.services.network_chembl import ChEMBLRawArtifactConnector
from app.services.network_common import (
    _IMPORTED_COMPOUND_SNAPSHOT_BLOCKER,
    _MAX_CHAINS_PER_QUERY,
    _UNLINKED_COMPOUND_CHILD_ERROR,
    _now_iso,
)
from app.services.network_open_targets import OpenTargetsRawArtifactConnector
from app.services.rag import DISCLAIMER

if TYPE_CHECKING:
    from app.repositories.protocols import NetworkTaskRepositoryProtocol


def _select_data_mode() -> DataMode:
    provider_name = get_settings().network_data_provider.strip().lower()
    return "live" if provider_name == "live" else "mock"


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
    from app.services import network as _facade

    for _ in range(3):
        task_id = f"network-{_facade.uuid4().hex}"
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
    from app.services import network as _facade

    repo = _facade._get_repository()
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
            _facade._build_import_snapshot(validated_request.disease_target_import)
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
    from app.services import network as _facade

    manifest_path = os.environ.get("NETWORK_OPEN_TARGETS_MANIFEST_PATH")
    if not manifest_path:
        raise ValueError("trusted Open Targets artifact manifest is not configured")
    OpenTargetsRawArtifactConnector.validate_trusted_manifest(
        raw_bytes,
        expected=metadata,
        manifest_path=Path(manifest_path),
    )
    snapshot = _facade.build_verified_disease_import_snapshot(
        raw_bytes,
        metadata=metadata,
        source_artifact_filename=source_artifact_filename,
        source_artifact_media_type=source_artifact_media_type,
    )
    _facade._persist_verified_raw_artifact(raw_bytes, snapshot.source_artifact_sha256)
    repo = _facade._get_repository()
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
    from app.services import network as _facade

    manifest_path = os.environ.get("NETWORK_CHEMBL_MANIFEST_PATH")
    if not manifest_path:
        raise ValueError("trusted ChEMBL artifact manifest is not configured")
    repo = _facade._get_repository()
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
    snapshot = _facade.build_verified_compound_import_snapshot(
        raw_bytes,
        metadata=metadata,
        source_artifact_filename=source_artifact_filename,
        source_artifact_media_type=source_artifact_media_type,
    )
    _facade._persist_verified_raw_artifact(raw_bytes, snapshot.source_artifact_sha256)
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
    from app.services import network as _facade

    target_lineage = _facade.build_target_lineage(
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
        readiness=_facade.assess_network_research_readiness(
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
    from app.services import network as _facade

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

    provider = _facade.select_network_provider(record.data_mode)
    result_payload = provider.build_result(
        task_id=record.task_id,
        query=record.query,
        analysis_type=record.analysis_type,
        chains=chains,
        enrichment=enrichment,
    )
    target_lineage = _facade.build_target_lineage(
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
            "chains": _facade.grade_chains_evidence(
                result_payload.chains, data_mode=record.data_mode
            ),
            "research_protocol": record.research_protocol,
            "target_lineage": target_lineage,
            "readiness": _facade.assess_network_research_readiness(
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
