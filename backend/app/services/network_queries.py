"""Read-side projections: task/result reads, listings, entity listing."""

from app.repositories.network_entities import NetworkEntityRepository
from app.schemas.network import (
    NetworkAnalysisResult,
    NetworkResultResponse,
    NetworkTargetAdjudication,
    NetworkTaskListResponse,
    NetworkTaskRecord,
    NetworkTaskSummary,
    TaskStatus,
)
from app.schemas.network_entities import NetworkEntitiesResponse
from app.services.network_common import _UNLINKED_COMPOUND_CHILD_ERROR


def _result_response(record: NetworkTaskRecord) -> NetworkResultResponse:
    from app.services import network as _facade

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
        adjudication=_facade._adjudication_summary(record),
        assembly_gate=_facade._assembly_gate_projection(record),
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
    from app.services import network as _facade

    repo = _facade._get_repository()
    current = repo.get_owned(task_id, reviewer_id)
    if current is None:
        return "not_found", None
    if _has_unlinked_compound_child(current):
        return "ok", _unlinked_compound_child_response(current)
    if current.status in {"completed", "failed"}:
        return "ok", _result_response(current)
    record = repo.advance(task_id, reviewer_id, _facade._advance_record)
    if record is None:
        return "not_found", None
    return "ok", _result_response(record)


def get_network_analysis_task(
    task_id: str,
    reviewer_id: str = "local-preview",
) -> tuple[str, NetworkResultResponse | None]:
    """Read an owner-scoped task without advancing its state machine."""
    from app.services import network as _facade

    record = _facade._get_repository().get_owned(task_id, reviewer_id)
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
    from app.services import network as _facade

    records = _facade._get_repository().list_records_for_owner(reviewer_id)
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
